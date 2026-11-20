"""MongoDB storage repository implementation (Lane C).

Provides persistence over IBM Cloud Databases for MongoDB or local MongoDB.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any
from cold_call_api.models import (
    ActiveCallModel,
    BriefModel,
    CallOutcomeEnum,
    CallStatusEnum,
    CompletedCallModel,
    ListModel,
    ProspectInput,
    ProspectModel,
    ProspectUpdateInput,
    ResearchJobModel,
    ResearchStatusEnum,
    normalize_prospect_key,
    utc_now_iso,
)
from cold_call_api.config import settings
from cold_call_api.storage.interface import StorageRepository, job_is_expired


_ACTIVE = (ResearchStatusEnum.QUEUED.value, ResearchStatusEnum.RUNNING.value)
_JOB_PROJECTION = {"_id": 0, "active": 0}


def _job_model(doc: dict[str, Any] | None) -> ResearchJobModel | None:
    return ResearchJobModel.model_validate(doc) if doc else None


class MongoStorageRepository(StorageRepository):
    """MongoDB implementation of the StorageRepository using PyMongo."""

    def __init__(self, uri: str, db_name: str = "cold_call_conversion") -> None:
        try:
            from pymongo import MongoClient  # type: ignore[import-untyped]
        except ImportError as err:
            raise RuntimeError("pymongo is required to use MongoStorageRepository.") from err

        self.client = MongoClient(uri, tz_aware=True)
        self.db = self.client[db_name]
        self._lists = self.db["lists"]
        self._prospects = self.db["prospects"]
        self._brief_cache = self.db["brief_cache"]
        self._jobs = self.db["research_jobs"]
        self._active_calls = self.db["active_calls"]
        self._completed_calls = self.db["completed_calls"]
        self._ensure_indexes()

    @staticmethod
    async def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking pymongo call off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _ensure_indexes(self) -> None:
        self._lists.create_index([("sellerId", 1), ("id", 1)], unique=True)
        self._prospects.create_index([("sellerId", 1), ("id", 1)], unique=True)
        self._prospects.create_index([("sellerId", 1), ("listId", 1), ("position", 1)])
        self._brief_cache.create_index([("prospectKey", 1)], unique=True)
        self._jobs.create_index([("sellerId", 1), ("prospectId", 1)])
        self._jobs.create_index([("status", 1)])
        # At most one active (queued/running) job per prospect revision. `active` is set on insert
        # and unset when the job finishes; a partial index on it enforces the constraint atomically.
        self._jobs.create_index(
            [("sellerId", 1), ("prospectId", 1), ("revision", 1)],
            unique=True,
            partialFilterExpression={"active": True},
            name="one_active_job_per_revision",
        )
        self._active_calls.create_index([("sellerId", 1)], unique=True)
        # Retried "end call" requests with the same Idempotency-Key must resolve to one call.
        self._completed_calls.create_index(
            [("sellerId", 1), ("idempotencyKey", 1)],
            unique=True,
            partialFilterExpression={"idempotencyKey": {"$type": "string"}},
            name="one_call_per_idempotency_key",
        )
        self._completed_calls.create_index([("sellerId", 1), ("endedAt", 1)])

    async def ensure_default_list(self, seller_id: str) -> ListModel:
        from pymongo.errors import DuplicateKeyError  # type: ignore[import-untyped]

        existing = await self._run(
            lambda: list(self._lists.find({"sellerId": seller_id}, {"_id": 0}).sort("id", 1).limit(1))
        )
        if existing:
            return ListModel.model_validate(existing[0])
        model = ListModel(id="list-default", sellerId=seller_id, name="My prospects")
        try:
            # Deterministic id + unique (sellerId, id) index makes concurrent calls converge.
            await self._run(self._lists.insert_one, model.model_dump())
            return model
        except DuplicateKeyError:
            doc = await self._run(self._lists.find_one, {"sellerId": seller_id, "id": "list-default"}, {"_id": 0})
            return ListModel.model_validate(doc) if doc else model

    async def get_lists(self, seller_id: str) -> list[ListModel]:
        docs = await self._run(lambda: list(self._lists.find({"sellerId": seller_id}, {"_id": 0})))
        return [ListModel.model_validate(doc) for doc in docs]

    async def get_list(self, seller_id: str, list_id: str) -> ListModel | None:
        doc = await self._run(self._lists.find_one, {"sellerId": seller_id, "id": list_id}, {"_id": 0})
        return ListModel.model_validate(doc) if doc else None

    async def create_list(self, seller_id: str, name: str) -> ListModel:
        list_id = f"list-{uuid.uuid4().hex[:8]}"
        model = ListModel(id=list_id, sellerId=seller_id, name=name.strip())
        await self._run(self._lists.insert_one, model.model_dump())
        return model

    async def update_list(self, seller_id: str, list_id: str, name: str) -> ListModel | None:
        res = await self._run(
            self._lists.find_one_and_update,
            {"sellerId": seller_id, "id": list_id},
            {"$set": {"name": name.strip()}},
            return_document=True,
            projection={"_id": 0},
        )
        return ListModel.model_validate(res) if res else None

    async def delete_list(self, seller_id: str, list_id: str) -> bool:
        # Check active call
        active = await self.get_active_call(seller_id)
        if active:
            p = await self.get_prospect(seller_id, active.prospectId)
            if p and p.listId == list_id:
                return False
        res = await self._run(self._lists.delete_one, {"sellerId": seller_id, "id": list_id})
        if res.deleted_count > 0:
            await self._run(self._prospects.delete_many, {"sellerId": seller_id, "listId": list_id})
            return True
        return False

    async def get_prospects(self, seller_id: str, list_id: str | None = None) -> list[ProspectModel]:
        query: dict[str, Any] = {"sellerId": seller_id}
        if list_id:
            query["listId"] = list_id
        docs = await self._run(
            lambda: list(self._prospects.find(query, {"_id": 0}).sort([("listId", 1), ("position", 1)]))
        )
        return [ProspectModel.model_validate(doc) for doc in docs]

    async def get_prospect(self, seller_id: str, prospect_id: str) -> ProspectModel | None:
        doc = await self._run(self._prospects.find_one, {"sellerId": seller_id, "id": prospect_id}, {"_id": 0})
        return ProspectModel.model_validate(doc) if doc else None

    async def create_prospects(
        self, seller_id: str, list_id: str, inputs: list[ProspectInput]
    ) -> tuple[list[ProspectModel], int]:
        l = await self.get_list(seller_id, list_id)
        if not l:
            raise ValueError(f"List {list_id} not found.")

        existing = await self.get_prospects(seller_id, list_id)
        existing_keys = {
            normalize_prospect_key(p.listId, p.name, p.company, p.role) for p in existing
        }
        max_pos = max((p.position for p in existing), default=-1)

        created: list[ProspectModel] = []
        duplicates = 0
        docs_to_insert: list[dict[str, Any]] = []

        for item in inputs:
            k = normalize_prospect_key(list_id, item.name, item.company, item.role)
            if k in existing_keys:
                duplicates += 1
                continue
            existing_keys.add(k)
            max_pos += 1
            pid = f"p-{uuid.uuid4().hex[:8]}"
            p = ProspectModel(
                id=pid,
                sellerId=seller_id,
                listId=list_id,
                name=item.name,
                company=item.company,
                role=item.role,
                phone=item.phone,
                notes=item.notes,
                companyDomain=item.companyDomain,
                position=max_pos,
                revision=0,
            )
            created.append(p)
            docs_to_insert.append(p.model_dump())

        if docs_to_insert:
            await self._run(self._prospects.insert_many, docs_to_insert)

        return created, duplicates

    async def update_prospect(
        self, seller_id: str, prospect_id: str, input_data: ProspectUpdateInput
    ) -> ProspectModel | None:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return None

        update_fields: dict[str, Any] = {
            "brief": None,
            "researchStatus": ResearchStatusEnum.NOT_STARTED.value,
            "researchError": None,
        }
        if input_data.name is not None:
            update_fields["name"] = input_data.name
        if input_data.company is not None:
            update_fields["company"] = input_data.company
        if input_data.role is not None:
            update_fields["role"] = input_data.role
        if input_data.phone is not None:
            update_fields["phone"] = input_data.phone
        if input_data.notes is not None:
            update_fields["notes"] = input_data.notes
        if input_data.companyDomain is not None:
            update_fields["companyDomain"] = input_data.companyDomain or None

        # $inc is atomic, so concurrent edits each get a distinct revision.
        doc = await self._run(
            self._prospects.find_one_and_update,
            {"sellerId": seller_id, "id": prospect_id},
            {"$set": update_fields, "$inc": {"revision": 1}},
            return_document=True,
            projection={"_id": 0},
        )
        return ProspectModel.model_validate(doc) if doc else None

    async def delete_prospect(self, seller_id: str, prospect_id: str) -> bool:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return False
        res = await self._run(self._prospects.delete_one, {"sellerId": seller_id, "id": prospect_id})
        return res.deleted_count > 0

    async def move_prospect(self, seller_id: str, prospect_id: str, direction: int) -> bool:
        p = await self.get_prospect(seller_id, prospect_id)
        if not p:
            return False
        list_prospects = await self.get_prospects(seller_id, p.listId)
        idx = next((i for i, x in enumerate(list_prospects) if x.id == prospect_id), -1)
        if idx < 0:
            return False
        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(list_prospects):
            return False
        other = list_prospects[target_idx]

        await self._run(
            self._prospects.update_one, {"sellerId": seller_id, "id": p.id}, {"$set": {"position": other.position}}
        )
        await self._run(
            self._prospects.update_one, {"sellerId": seller_id, "id": other.id}, {"$set": {"position": p.position}}
        )
        return True

    async def update_prospect_research(
        self,
        seller_id: str,
        prospect_id: str,
        revision: int,
        status: ResearchStatusEnum,
        brief: BriefModel | None,
        error: str | None,
    ) -> bool:
        update_fields: dict[str, Any] = {
            "researchStatus": status.value,
            "brief": brief.model_dump() if brief else None,
            "researchError": error,
        }
        res = await self._run(
            self._prospects.update_one,
            {"sellerId": seller_id, "id": prospect_id, "revision": revision},
            {"$set": update_fields},
        )
        # matched_count: an identical rewrite still means the revision matched
        return res.matched_count > 0

    async def get_cached_entry(
        self, prospect_key: str, max_age_days: int = 30
    ) -> tuple[BriefModel, ResearchStatusEnum | None] | None:
        doc = await self._run(self._brief_cache.find_one, {"prospectKey": prospect_key}, {"_id": 0})
        if not doc:
            return None
        saved_at = datetime.fromisoformat(doc["savedAt"])
        if datetime.now(timezone.utc) - saved_at > timedelta(days=max_age_days):
            await self._run(self._brief_cache.delete_one, {"prospectKey": prospect_key})
            return None
        stored = doc.get("status")
        return BriefModel.model_validate(doc["brief"]), (ResearchStatusEnum(stored) if stored else None)

    async def save_cached_briefing(
        self, prospect_key: str, brief: BriefModel, status: ResearchStatusEnum | None = None
    ) -> None:
        await self._run(
            self._brief_cache.update_one,
            {"prospectKey": prospect_key},
            {"$set": {"brief": brief.model_dump(), "savedAt": utc_now_iso(), "status": status.value if status else None}},
            upsert=True,
        )

    async def enqueue_research_jobs(self, seller_id: str, prospect_ids: list[str]) -> list[ResearchJobModel]:
        from pymongo.errors import DuplicateKeyError  # type: ignore[import-untyped]

        jobs: list[ResearchJobModel] = []
        for pid in prospect_ids:
            p = await self.get_prospect(seller_id, pid)
            if not p:
                continue
            active = await self.get_active_call(seller_id)
            if active and active.prospectId == pid:
                continue

            # Fail any expired active job (crash/restart) so it no longer blocks this prospect.
            existing = await self._run(
                lambda: list(
                    self._jobs.find(
                        {
                            "sellerId": seller_id,
                            "prospectId": pid,
                            "revision": p.revision,
                            "status": {"$in": list(_ACTIVE)},
                        },
                        {"_id": 0},
                    )
                )
            )
            for doc in existing:
                if job_is_expired(
                    doc.get("leaseExpiresAt"), doc.get("createdAt", ""), settings.research_lease_seconds
                ):
                    await self._run(
                        self._jobs.update_one,
                        {"id": doc["id"], "status": {"$in": list(_ACTIVE)}},
                        {
                            "$set": {
                                "status": ResearchStatusEnum.FAILED.value,
                                "lastError": "Job lease expired.",
                                "leaseExpiresAt": None,
                            },
                            "$unset": {"active": ""},
                        },
                    )

            job = ResearchJobModel(
                id=f"job-{uuid.uuid4().hex[:8]}",
                prospectId=pid,
                sellerId=seller_id,
                revision=p.revision,
                status=ResearchStatusEnum.QUEUED,
            )
            try:
                # The partial unique index makes this the atomic "already queued" check.
                await self._run(self._jobs.insert_one, {**job.model_dump(), "active": True})
            except DuplicateKeyError:
                continue

            await self._run(
                self._prospects.update_one,
                {"sellerId": seller_id, "id": pid},
                {"$set": {"researchStatus": ResearchStatusEnum.RUNNING.value, "researchError": None}},
            )
            jobs.append(job)
        return jobs

    async def claim_research_job(
        self, worker_id: str, lease_seconds: int = 90, job_id: str | None = None
    ) -> ResearchJobModel | None:
        now = datetime.now(timezone.utc)
        lease_exp = (now + timedelta(seconds=lease_seconds)).isoformat()
        query: dict[str, Any] = {"status": ResearchStatusEnum.QUEUED.value}
        if job_id is not None:
            query["id"] = job_id
        else:  # a poller must not take jobs still in retry backoff (missing/None notBefore matches None)
            query["$or"] = [{"notBefore": None}, {"notBefore": {"$lte": now.isoformat()}}]
        doc = await self._run(
            self._jobs.find_one_and_update,
            query,
            {
                "$set": {
                    "status": ResearchStatusEnum.RUNNING.value,
                    "claimedBy": worker_id,
                    "leaseExpiresAt": lease_exp,
                    "notBefore": None,
                },
                "$inc": {"attempts": 1},
            },
            return_document=True,
            projection=_JOB_PROJECTION,
        )
        return _job_model(doc)

    async def requeue_research_job(
        self, job_id: str, error: str, lease_seconds: int, delay_seconds: float = 0
    ) -> bool:
        now = datetime.now(timezone.utc)
        lease_exp = (now + timedelta(seconds=lease_seconds)).isoformat()
        not_before = (now + timedelta(seconds=delay_seconds)).isoformat() if delay_seconds > 0 else None
        res = await self._run(
            self._jobs.update_one,
            {"id": job_id, "status": ResearchStatusEnum.RUNNING.value},
            {
                "$set": {
                    "status": ResearchStatusEnum.QUEUED.value,
                    "lastError": error,
                    "leaseExpiresAt": lease_exp,
                    "notBefore": not_before,
                }
            },
        )
        return res.matched_count > 0

    async def finish_research_job(
        self, job_id: str, status: ResearchStatusEnum, error: str | None = None
    ) -> None:
        await self._run(
            self._jobs.update_one,
            {"id": job_id},
            {
                "$set": {"status": status.value, "lastError": error, "leaseExpiresAt": None},
                "$unset": {"active": ""},
            },
        )

    async def get_research_status(self, seller_id: str, prospect_id: str) -> ResearchJobModel | None:
        doc = await self._run(
            self._jobs.find_one,
            {"sellerId": seller_id, "prospectId": prospect_id},
            _JOB_PROJECTION,
            sort=[("createdAt", -1)],
        )
        return _job_model(doc)

    async def get_active_call(self, seller_id: str) -> ActiveCallModel | None:
        doc = await self._run(self._active_calls.find_one, {"sellerId": seller_id}, {"_id": 0, "sellerId": 0})
        return ActiveCallModel.model_validate(doc) if doc else None

    async def connect_call(self, seller_id: str, prospect_id: str) -> ActiveCallModel:
        from pymongo.errors import DuplicateKeyError  # type: ignore[import-untyped]

        p = await self.get_prospect(seller_id, prospect_id)
        if not p:
            raise ValueError(f"Prospect {prospect_id} not found.")
        active = await self.get_active_call(seller_id)
        if active:
            raise ValueError("A call is already active for this seller.")

        call = ActiveCallModel(prospectId=prospect_id, startedAt=utc_now_iso())
        try:
            await self._run(self._active_calls.insert_one, {"sellerId": seller_id, **call.model_dump()})
        except DuplicateKeyError as err:
            raise ValueError("A call is already active for this seller.") from err
        return call

    async def end_call(
        self, seller_id: str, outcome: CallOutcomeEnum, idempotency_key: str | None = None
    ) -> CompletedCallModel | None:
        from pymongo.errors import DuplicateKeyError  # type: ignore[import-untyped]

        async def replay() -> CompletedCallModel | None:
            if not idempotency_key:
                return None
            doc = await self._run(
                self._completed_calls.find_one,
                {"sellerId": seller_id, "idempotencyKey": idempotency_key},
                {"_id": 0},
            )
            return CompletedCallModel.model_validate(doc) if doc else None

        # Atomically claim the active call: of N concurrent "end" requests exactly one
        # gets the document back; the rest see no active call.
        claimed = await self._run(
            self._active_calls.find_one_and_delete, {"sellerId": seller_id}, projection={"_id": 0, "sellerId": 0}
        )
        if not claimed:
            return await replay()
        active = ActiveCallModel.model_validate(claimed)

        completed = CompletedCallModel(
            id=f"call-{uuid.uuid4().hex[:8]}",
            sellerId=seller_id,
            prospectId=active.prospectId,
            startedAt=active.startedAt,
            endedAt=utc_now_iso(),
            outcome=outcome,
            idempotencyKey=idempotency_key,
        )
        try:
            await self._run(self._completed_calls.insert_one, completed.model_dump())
        except DuplicateKeyError:
            # This key already ended an earlier call: restore the claimed call and replay the original.
            try:
                await self._run(self._active_calls.insert_one, {"sellerId": seller_id, **active.model_dump()})
            except DuplicateKeyError:
                pass  # the seller already connected a new call meanwhile; keep that one
            return await replay()
        await self._run(
            self._prospects.update_one,
            {"sellerId": seller_id, "id": active.prospectId},
            {"$set": {"callStatus": CallStatusEnum.CALLED.value, "outcome": outcome.value}},
        )
        return completed

    async def reset_call(self, seller_id: str, prospect_id: str) -> bool:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return False
        res = await self._run(
            self._prospects.update_one,
            {"sellerId": seller_id, "id": prospect_id},
            {"$set": {"callStatus": CallStatusEnum.READY.value, "outcome": None}},
        )
        # matched_count: resetting an already-ready prospect is still a success
        return res.matched_count > 0

    async def list_completed_calls(self, seller_id: str) -> list[CompletedCallModel]:
        docs = await self._run(
            lambda: list(self._completed_calls.find({"sellerId": seller_id}, {"_id": 0}).sort("endedAt", 1))
        )
        return [CompletedCallModel.model_validate(doc) for doc in docs]

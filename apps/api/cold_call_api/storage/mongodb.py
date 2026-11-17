"""MongoDB storage repository implementation (Lane C).

Provides persistence over IBM Cloud Databases for MongoDB or local MongoDB.
"""

from __future__ import annotations

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
from cold_call_api.storage.interface import StorageRepository


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

    def _ensure_indexes(self) -> None:
        self._lists.create_index([("sellerId", 1), ("id", 1)], unique=True)
        self._prospects.create_index([("sellerId", 1), ("id", 1)], unique=True)
        self._prospects.create_index([("sellerId", 1), ("listId", 1), ("position", 1)])
        self._brief_cache.create_index([("prospectKey", 1)], unique=True)
        self._jobs.create_index([("sellerId", 1), ("prospectId", 1)])
        self._jobs.create_index([("status", 1)])
        self._active_calls.create_index([("sellerId", 1)], unique=True)
        self._completed_calls.create_index([("sellerId", 1), ("idempotencyKey", 1)])

    async def get_lists(self, seller_id: str) -> list[ListModel]:
        cursor = self._lists.find({"sellerId": seller_id}, {"_id": 0})
        return [ListModel.model_validate(doc) for doc in cursor]

    async def get_list(self, seller_id: str, list_id: str) -> ListModel | None:
        doc = self._lists.find_one({"sellerId": seller_id, "id": list_id}, {"_id": 0})
        return ListModel.model_validate(doc) if doc else None

    async def create_list(self, seller_id: str, name: str) -> ListModel:
        list_id = f"list-{uuid.uuid4().hex[:8]}"
        model = ListModel(id=list_id, sellerId=seller_id, name=name.strip())
        self._lists.insert_one(model.model_dump())
        return model

    async def update_list(self, seller_id: str, list_id: str, name: str) -> ListModel | None:
        res = self._lists.find_one_and_update(
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
        res = self._lists.delete_one({"sellerId": seller_id, "id": list_id})
        if res.deleted_count > 0:
            self._prospects.delete_many({"sellerId": seller_id, "listId": list_id})
            return True
        return False

    async def get_prospects(self, seller_id: str, list_id: str | None = None) -> list[ProspectModel]:
        query: dict[str, Any] = {"sellerId": seller_id}
        if list_id:
            query["listId"] = list_id
        cursor = self._prospects.find(query, {"_id": 0}).sort([("listId", 1), ("position", 1)])
        return [ProspectModel.model_validate(doc) for doc in cursor]

    async def get_prospect(self, seller_id: str, prospect_id: str) -> ProspectModel | None:
        doc = self._prospects.find_one({"sellerId": seller_id, "id": prospect_id}, {"_id": 0})
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
                position=max_pos,
                revision=0,
            )
            created.append(p)
            docs_to_insert.append(p.model_dump())

        if docs_to_insert:
            self._prospects.insert_many(docs_to_insert)

        return created, duplicates

    async def update_prospect(
        self, seller_id: str, prospect_id: str, input_data: ProspectUpdateInput
    ) -> ProspectModel | None:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return None

        p = await self.get_prospect(seller_id, prospect_id)
        if not p:
            return None

        update_fields: dict[str, Any] = {
            "revision": p.revision + 1,
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

        doc = self._prospects.find_one_and_update(
            {"sellerId": seller_id, "id": prospect_id},
            {"$set": update_fields},
            return_document=True,
            projection={"_id": 0},
        )
        return ProspectModel.model_validate(doc) if doc else None

    async def delete_prospect(self, seller_id: str, prospect_id: str) -> bool:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return False
        res = self._prospects.delete_one({"sellerId": seller_id, "id": prospect_id})
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

        self._prospects.update_one(
            {"sellerId": seller_id, "id": p.id}, {"$set": {"position": other.position}}
        )
        self._prospects.update_one(
            {"sellerId": seller_id, "id": other.id}, {"$set": {"position": p.position}}
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
        res = self._prospects.update_one(
            {"sellerId": seller_id, "id": prospect_id, "revision": revision},
            {"$set": update_fields},
        )
        return res.modified_count > 0

    async def get_cached_briefing(self, prospect_key: str, max_age_days: int = 30) -> BriefModel | None:
        doc = self._brief_cache.find_one({"prospectKey": prospect_key}, {"_id": 0})
        if not doc:
            return None
        saved_at = datetime.fromisoformat(doc["savedAt"])
        if datetime.now(timezone.utc) - saved_at > timedelta(days=max_age_days):
            self._brief_cache.delete_one({"prospectKey": prospect_key})
            return None
        return BriefModel.model_validate(doc["brief"])

    async def save_cached_briefing(self, prospect_key: str, brief: BriefModel) -> None:
        self._brief_cache.update_one(
            {"prospectKey": prospect_key},
            {"$set": {"brief": brief.model_dump(), "savedAt": utc_now_iso()}},
            upsert=True,
        )

    async def enqueue_research_jobs(self, seller_id: str, prospect_ids: list[str]) -> list[ResearchJobModel]:
        jobs: list[ResearchJobModel] = []
        for pid in prospect_ids:
            p = await self.get_prospect(seller_id, pid)
            if not p:
                continue
            active = await self.get_active_call(seller_id)
            if active and active.prospectId == pid:
                continue

            self._prospects.update_one(
                {"sellerId": seller_id, "id": pid},
                {"$set": {"researchStatus": ResearchStatusEnum.RUNNING.value, "researchError": None}},
            )
            job = ResearchJobModel(
                id=f"job-{uuid.uuid4().hex[:8]}",
                prospectId=pid,
                sellerId=seller_id,
                revision=p.revision,
                status=ResearchStatusEnum.QUEUED,
            )
            self._jobs.insert_one(job.model_dump())
            jobs.append(job)
        return jobs

    async def claim_research_job(self, worker_id: str, lease_seconds: int = 90) -> ResearchJobModel | None:
        now = datetime.now(timezone.utc)
        lease_exp = (now + timedelta(seconds=lease_seconds)).isoformat()
        doc = self._jobs.find_one_and_update(
            {"status": ResearchStatusEnum.QUEUED.value},
            {
                "$set": {
                    "status": ResearchStatusEnum.RUNNING.value,
                    "claimedBy": worker_id,
                    "leaseExpiresAt": lease_exp,
                },
                "$inc": {"attempts": 1},
            },
            return_document=True,
            projection={"_id": 0},
        )
        return ResearchJobModel.model_validate(doc) if doc else None

    async def finish_research_job(
        self, job_id: str, status: ResearchStatusEnum, error: str | None = None
    ) -> None:
        self._jobs.update_one(
            {"id": job_id},
            {"$set": {"status": status.value, "lastError": error, "leaseExpiresAt": None}},
        )

    async def get_research_status(self, seller_id: str, prospect_id: str) -> ResearchJobModel | None:
        doc = self._jobs.find_one(
            {"sellerId": seller_id, "prospectId": prospect_id},
            {"_id": 0},
            sort=[("createdAt", -1)],
        )
        return ResearchJobModel.model_validate(doc) if doc else None

    async def get_active_call(self, seller_id: str) -> ActiveCallModel | None:
        doc = self._active_calls.find_one({"sellerId": seller_id}, {"_id": 0})
        return ActiveCallModel.model_validate(doc) if doc else None

    async def connect_call(self, seller_id: str, prospect_id: str) -> ActiveCallModel:
        p = await self.get_prospect(seller_id, prospect_id)
        if not p:
            raise ValueError(f"Prospect {prospect_id} not found.")
        active = await self.get_active_call(seller_id)
        if active:
            raise ValueError("A call is already active for this seller.")

        call = ActiveCallModel(prospectId=prospect_id, startedAt=utc_now_iso())
        self._active_calls.insert_one({"sellerId": seller_id, **call.model_dump()})
        return call

    async def end_call(
        self, seller_id: str, outcome: CallOutcomeEnum, idempotency_key: str | None = None
    ) -> CompletedCallModel | None:
        active = await self.get_active_call(seller_id)
        if not active:
            if idempotency_key:
                doc = self._completed_calls.find_one(
                    {"sellerId": seller_id, "idempotencyKey": idempotency_key}, {"_id": 0}
                )
                return CompletedCallModel.model_validate(doc) if doc else None
            return None

        completed = CompletedCallModel(
            id=f"call-{uuid.uuid4().hex[:8]}",
            sellerId=seller_id,
            prospectId=active.prospectId,
            startedAt=active.startedAt,
            endedAt=utc_now_iso(),
            outcome=outcome,
            idempotencyKey=idempotency_key,
        )
        self._completed_calls.insert_one(completed.model_dump())
        self._active_calls.delete_one({"sellerId": seller_id})
        self._prospects.update_one(
            {"sellerId": seller_id, "id": active.prospectId},
            {"$set": {"callStatus": CallStatusEnum.CALLED.value, "outcome": outcome.value}},
        )
        return completed

    async def reset_call(self, seller_id: str, prospect_id: str) -> bool:
        active = await self.get_active_call(seller_id)
        if active and active.prospectId == prospect_id:
            return False
        res = self._prospects.update_one(
            {"sellerId": seller_id, "id": prospect_id},
            {"$set": {"callStatus": CallStatusEnum.READY.value, "outcome": None}},
        )
        return res.modified_count > 0

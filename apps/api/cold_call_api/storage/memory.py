"""In-memory storage repository implementation (Lane C).

Thread-safe in-memory data store for local development, fast integration testing,
and demo execution without requiring an external database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
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


class MemoryStorageRepository(StorageRepository):
    """In-memory implementation of the StorageRepository."""

    def __init__(self, seed: bool = True) -> None:
        self._lock = asyncio.Lock()
        self._lists: dict[str, ListModel] = {}  # id -> ListModel
        self._prospects: dict[str, ProspectModel] = {}  # id -> ProspectModel
        self._brief_cache: dict[str, tuple[BriefModel, datetime]] = {}  # prospect_key -> (brief, saved_at)
        self._jobs: dict[str, ResearchJobModel] = {}  # job_id -> ResearchJobModel
        self._active_calls: dict[str, ActiveCallModel] = {}  # seller_id -> ActiveCallModel
        self._completed_calls: list[CompletedCallModel] = []
        if seed:
            self._seed_default_data()

    def _seed_default_data(self) -> None:
        default_seller = "seller-default"
        # Seed lists
        l1 = ListModel(id="list-outreach", sellerId=default_seller, name="October outreach")
        l2 = ListModel(id="list-accounts", sellerId=default_seller, name="Strategic accounts")
        self._lists[l1.id] = l1
        self._lists[l2.id] = l2

        # Seed sample prospects matching frontend seed data
        seeds = [
            # No seeded prospect is READY/PARTIAL: that status requires a real brief, and none is attached.
            ("p-maya", "Maya Chen", "Northstar Logistics", "VP of Information Technology", "list-outreach", ResearchStatusEnum.NOT_STARTED),
            ("p-jordan", "Jordan Ellis", "Meridian Consulting", "Director of IT", "list-outreach", ResearchStatusEnum.NOT_STARTED),
            ("p-alex", "Alex Morgan", "Atlas Manufacturing", "Head of Infrastructure", "list-outreach", ResearchStatusEnum.NOT_STARTED),
            ("p-sam", "Sam Rivera", "Cedar Health Systems", "IT Operations Manager", "list-outreach", ResearchStatusEnum.NOT_STARTED),
            ("p-priya", "Priya Shah", "Fieldwork Studio", "Chief Technology Officer", "list-outreach", ResearchStatusEnum.FAILED),
            ("p-eli", "Eli Brooks", "Harbor Financial", "Director of Technology", "list-outreach", ResearchStatusEnum.NOT_STARTED),
            ("p-robin", "Robin Park", "Meridian Consulting", "Chief Operating Officer", "list-accounts", ResearchStatusEnum.NOT_STARTED),
            ("p-taylor", "Taylor Reed", "Atlas Manufacturing", "IT Director", "list-accounts", ResearchStatusEnum.NOT_STARTED),
        ]

        for idx, (pid, name, company, role, lid, status) in enumerate(seeds):
            p = ProspectModel(
                id=pid,
                sellerId=default_seller,
                listId=lid,
                name=name,
                company=company,
                role=role,
                phone=f"+1 (202) 555-01{idx + 10:02d}",
                notes="Sample seller notes." if "Northstar" in company else "",
                position=idx,
                revision=0,
                researchStatus=status,
                callStatus=CallStatusEnum.CALLED if pid == "p-eli" else CallStatusEnum.READY,
                outcome=CallOutcomeEnum.NO_ANSWER if pid == "p-eli" else None,
                researchError="Sample timeout error." if status == ResearchStatusEnum.FAILED else None,
            )
            self._prospects[pid] = p

    # --- Lists ---
    async def ensure_default_list(self, seller_id: str) -> ListModel:
        async with self._lock:
            existing = [l for l in self._lists.values() if l.sellerId == seller_id]
            if existing:
                return existing[0]
            l = ListModel(id=f"list-{uuid.uuid4().hex[:8]}", sellerId=seller_id, name="My prospects")
            self._lists[l.id] = l
            return l

    async def get_lists(self, seller_id: str) -> list[ListModel]:
        async with self._lock:
            return [l for l in self._lists.values() if l.sellerId == seller_id]

    async def get_list(self, seller_id: str, list_id: str) -> ListModel | None:
        async with self._lock:
            l = self._lists.get(list_id)
            if l and l.sellerId == seller_id:
                return l
            return None

    async def create_list(self, seller_id: str, name: str) -> ListModel:
        async with self._lock:
            list_id = f"list-{uuid.uuid4().hex[:8]}"
            l = ListModel(id=list_id, sellerId=seller_id, name=name.strip())
            self._lists[list_id] = l
            return l

    async def update_list(self, seller_id: str, list_id: str, name: str) -> ListModel | None:
        async with self._lock:
            l = self._lists.get(list_id)
            if not l or l.sellerId != seller_id:
                return None
            updated = l.model_copy(update={"name": name.strip()})
            self._lists[list_id] = updated
            return updated

    async def delete_list(self, seller_id: str, list_id: str) -> bool:
        async with self._lock:
            l = self._lists.get(list_id)
            if not l or l.sellerId != seller_id:
                return False
            # Check if active call is on this list
            active = self._active_calls.get(seller_id)
            if active:
                p = self._prospects.get(active.prospectId)
                if p and p.listId == list_id:
                    return False
            # Delete list and its prospects
            del self._lists[list_id]
            prospect_ids_to_del = [pid for pid, pr in self._prospects.items() if pr.listId == list_id and pr.sellerId == seller_id]
            for pid in prospect_ids_to_del:
                del self._prospects[pid]
            return True

    # --- Prospects ---
    async def get_prospects(self, seller_id: str, list_id: str | None = None) -> list[ProspectModel]:
        async with self._lock:
            results = [p for p in self._prospects.values() if p.sellerId == seller_id]
            if list_id:
                results = [p for p in results if p.listId == list_id]
            return sorted(results, key=lambda x: (x.listId, x.position))

    async def get_prospect(self, seller_id: str, prospect_id: str) -> ProspectModel | None:
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if p and p.sellerId == seller_id:
                return p
            return None

    async def create_prospects(
        self, seller_id: str, list_id: str, inputs: list[ProspectInput]
    ) -> tuple[list[ProspectModel], int]:
        async with self._lock:
            l = self._lists.get(list_id)
            if not l or l.sellerId != seller_id:
                raise ValueError(f"List {list_id} does not exist or not owned by seller.")

            existing_keys = {
                normalize_prospect_key(p.listId, p.name, p.company, p.role)
                for p in self._prospects.values()
                if p.sellerId == seller_id and p.listId == list_id
            }

            max_pos = max(
                (p.position for p in self._prospects.values() if p.sellerId == seller_id and p.listId == list_id),
                default=-1,
            )

            created: list[ProspectModel] = []
            duplicates = 0

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
                self._prospects[pid] = p
                created.append(p)

            return created, duplicates

    async def update_prospect(
        self, seller_id: str, prospect_id: str, input_data: ProspectUpdateInput
    ) -> ProspectModel | None:
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                return None
            # Reject if currently on active call
            active = self._active_calls.get(seller_id)
            if active and active.prospectId == prospect_id:
                return None

            updates: dict[str, object] = {
                "revision": p.revision + 1,
                "brief": None,
                "researchStatus": ResearchStatusEnum.NOT_STARTED,
                "researchError": None,
            }
            if input_data.name is not None:
                updates["name"] = input_data.name
            if input_data.company is not None:
                updates["company"] = input_data.company
            if input_data.role is not None:
                updates["role"] = input_data.role
            if input_data.phone is not None:
                updates["phone"] = input_data.phone
            if input_data.notes is not None:
                updates["notes"] = input_data.notes

            updated = p.model_copy(update=updates)
            self._prospects[prospect_id] = updated
            return updated

    async def delete_prospect(self, seller_id: str, prospect_id: str) -> bool:
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                return False
            active = self._active_calls.get(seller_id)
            if active and active.prospectId == prospect_id:
                return False
            del self._prospects[prospect_id]
            return True

    async def move_prospect(self, seller_id: str, prospect_id: str, direction: int) -> bool:
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                return False
            list_prospects = sorted(
                [pr for pr in self._prospects.values() if pr.sellerId == seller_id and pr.listId == p.listId],
                key=lambda x: x.position,
            )
            idx = next((i for i, x in enumerate(list_prospects) if x.id == prospect_id), -1)
            if idx < 0:
                return False
            target_idx = idx + direction
            if target_idx < 0 or target_idx >= len(list_prospects):
                return False
            other = list_prospects[target_idx]
            # Swap positions
            self._prospects[p.id] = p.model_copy(update={"position": other.position})
            self._prospects[other.id] = other.model_copy(update={"position": p.position})
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
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                return False
            # Stale-result protection: only apply if revision matches exactly
            if p.revision != revision:
                return False

            updates: dict[str, object] = {
                "researchStatus": status,
                "brief": brief,
                "researchError": error,
            }
            self._prospects[prospect_id] = p.model_copy(update=updates)
            return True

    # --- Briefings Cache ---
    async def get_cached_briefing(self, prospect_key: str, max_age_days: int = 30) -> BriefModel | None:
        async with self._lock:
            entry = self._brief_cache.get(prospect_key)
            if not entry:
                return None
            brief, saved_at = entry
            if datetime.now(timezone.utc) - saved_at > timedelta(days=max_age_days):
                del self._brief_cache[prospect_key]
                return None
            return brief

    async def save_cached_briefing(self, prospect_key: str, brief: BriefModel) -> None:
        async with self._lock:
            self._brief_cache[prospect_key] = (brief, datetime.now(timezone.utc))

    # --- Research Jobs Queue ---
    async def enqueue_research_jobs(self, seller_id: str, prospect_ids: list[str]) -> list[ResearchJobModel]:
        async with self._lock:
            created_jobs: list[ResearchJobModel] = []
            for pid in prospect_ids:
                p = self._prospects.get(pid)
                if not p or p.sellerId != seller_id:
                    continue
                # Do not re-enqueue if active call on it
                active = self._active_calls.get(seller_id)
                if active and active.prospectId == pid:
                    continue
                # Idempotent: a live job for this exact revision is already in flight.
                # Jobs whose lease expired (crash/restart) are failed and replaced.
                live = False
                for j in list(self._jobs.values()):
                    if (
                        j.prospectId == pid
                        and j.revision == p.revision
                        and j.status in (ResearchStatusEnum.QUEUED, ResearchStatusEnum.RUNNING)
                    ):
                        if job_is_expired(j.leaseExpiresAt, j.createdAt, settings.research_lease_seconds):
                            self._jobs[j.id] = j.model_copy(
                                update={
                                    "status": ResearchStatusEnum.FAILED,
                                    "lastError": "Job lease expired.",
                                    "leaseExpiresAt": None,
                                }
                            )
                        else:
                            live = True
                if live:
                    continue

                # Set prospect status to RUNNING
                self._prospects[pid] = p.model_copy(
                    update={"researchStatus": ResearchStatusEnum.RUNNING, "researchError": None}
                )

                job_id = f"job-{uuid.uuid4().hex[:8]}"
                job = ResearchJobModel(
                    id=job_id,
                    prospectId=pid,
                    sellerId=seller_id,
                    revision=p.revision,
                    status=ResearchStatusEnum.QUEUED,
                )
                self._jobs[job_id] = job
                created_jobs.append(job)
            return created_jobs

    async def claim_research_job(
        self, worker_id: str, lease_seconds: int = 90, job_id: str | None = None
    ) -> ResearchJobModel | None:
        async with self._lock:
            now = datetime.now(timezone.utc)
            for j in self._jobs.values():
                if j.status == ResearchStatusEnum.QUEUED and (job_id is None or j.id == job_id):
                    lease_exp = (now + timedelta(seconds=lease_seconds)).isoformat()
                    claimed = j.model_copy(
                        update={
                            "status": ResearchStatusEnum.RUNNING,
                            "claimedBy": worker_id,
                            "leaseExpiresAt": lease_exp,
                            "attempts": j.attempts + 1,
                        }
                    )
                    self._jobs[j.id] = claimed
                    return claimed
            return None

    async def finish_research_job(
        self, job_id: str, status: ResearchStatusEnum, error: str | None = None
    ) -> None:
        async with self._lock:
            j = self._jobs.get(job_id)
            if j:
                self._jobs[job_id] = j.model_copy(
                    update={"status": status, "lastError": error, "leaseExpiresAt": None}
                )

    async def get_research_status(self, seller_id: str, prospect_id: str) -> ResearchJobModel | None:
        async with self._lock:
            # Find the newest job for this prospect
            matching = [
                j for j in self._jobs.values() if j.sellerId == seller_id and j.prospectId == prospect_id
            ]
            if not matching:
                return None
            return sorted(matching, key=lambda x: x.createdAt, reverse=True)[0]

    # --- Calls ---
    async def get_active_call(self, seller_id: str) -> ActiveCallModel | None:
        async with self._lock:
            return self._active_calls.get(seller_id)

    async def connect_call(self, seller_id: str, prospect_id: str) -> ActiveCallModel:
        async with self._lock:
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                raise ValueError(f"Prospect {prospect_id} not found.")
            if seller_id in self._active_calls:
                raise ValueError("A call is already active for this seller.")

            call = ActiveCallModel(prospectId=prospect_id, startedAt=utc_now_iso())
            self._active_calls[seller_id] = call
            return call

    async def end_call(
        self, seller_id: str, outcome: CallOutcomeEnum, idempotency_key: str | None = None
    ) -> CompletedCallModel | None:
        async with self._lock:
            active = self._active_calls.get(seller_id)
            if not active:
                if idempotency_key:
                    # Check if already ended with idempotency key
                    for c in reversed(self._completed_calls):
                        if c.sellerId == seller_id and c.idempotencyKey == idempotency_key:
                            return c
                return None

            p = self._prospects.get(active.prospectId)
            now = utc_now_iso()
            completed = CompletedCallModel(
                id=f"call-{uuid.uuid4().hex[:8]}",
                sellerId=seller_id,
                prospectId=active.prospectId,
                startedAt=active.startedAt,
                endedAt=now,
                outcome=outcome,
                idempotencyKey=idempotency_key,
            )
            self._completed_calls.append(completed)
            del self._active_calls[seller_id]

            if p:
                self._prospects[p.id] = p.model_copy(
                    update={"callStatus": CallStatusEnum.CALLED, "outcome": outcome}
                )

            return completed

    async def reset_call(self, seller_id: str, prospect_id: str) -> bool:
        async with self._lock:
            active = self._active_calls.get(seller_id)
            if active and active.prospectId == prospect_id:
                return False
            p = self._prospects.get(prospect_id)
            if not p or p.sellerId != seller_id:
                return False
            self._prospects[prospect_id] = p.model_copy(
                update={"callStatus": CallStatusEnum.READY, "outcome": None}
            )
            return True

    async def list_completed_calls(self, seller_id: str) -> list[CompletedCallModel]:
        async with self._lock:
            calls = [c for c in self._completed_calls if c.sellerId == seller_id]
            return sorted(calls, key=lambda c: c.endedAt)

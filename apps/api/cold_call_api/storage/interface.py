"""Abstract storage interface for Cold Call Conversion backend (Lane C)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from cold_call_api.models import (
    ActiveCallModel,
    BriefModel,
    CallOutcomeEnum,
    CompletedCallModel,
    ListModel,
    ProspectInput,
    ProspectModel,
    ProspectUpdateInput,
    ResearchJobModel,
    ResearchStatusEnum,
)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def job_is_expired(
    lease_expires_at: str | None, created_at: str, lease_seconds: int, now: datetime | None = None
) -> bool:
    """An active job is expired when its lease ran out (or, with no lease, it is older than one lease)."""
    now = now or datetime.now(timezone.utc)
    try:
        if lease_expires_at:
            return now > _parse_iso(lease_expires_at)
        return now > _parse_iso(created_at) + timedelta(seconds=lease_seconds)
    except ValueError:
        return True


class StorageRepository(ABC):
    """Abstract interface defining all data operations required by the backend."""

    # --- Lists ---
    @abstractmethod
    async def ensure_default_list(self, seller_id: str) -> ListModel:
        """Return the seller's first list, creating a default one if they have none. Idempotent."""
        pass

    @abstractmethod
    async def get_lists(self, seller_id: str) -> list[ListModel]:
        pass

    @abstractmethod
    async def get_list(self, seller_id: str, list_id: str) -> ListModel | None:
        pass

    @abstractmethod
    async def create_list(self, seller_id: str, name: str) -> ListModel:
        pass

    @abstractmethod
    async def update_list(self, seller_id: str, list_id: str, name: str) -> ListModel | None:
        pass

    @abstractmethod
    async def delete_list(self, seller_id: str, list_id: str) -> bool:
        pass

    # --- Prospects ---
    @abstractmethod
    async def get_prospects(self, seller_id: str, list_id: str | None = None) -> list[ProspectModel]:
        pass

    @abstractmethod
    async def get_prospect(self, seller_id: str, prospect_id: str) -> ProspectModel | None:
        pass

    @abstractmethod
    async def create_prospects(
        self, seller_id: str, list_id: str, inputs: list[ProspectInput]
    ) -> tuple[list[ProspectModel], int]:
        """Creates prospects, skipping duplicates within the same list. Returns (created, duplicates_skipped)."""
        pass

    @abstractmethod
    async def update_prospect(
        self, seller_id: str, prospect_id: str, input_data: ProspectUpdateInput
    ) -> ProspectModel | None:
        """Updates prospect fields, increments revision, invalidates previous brief."""
        pass

    @abstractmethod
    async def delete_prospect(self, seller_id: str, prospect_id: str) -> bool:
        pass

    @abstractmethod
    async def move_prospect(self, seller_id: str, prospect_id: str, direction: int) -> bool:
        pass

    @abstractmethod
    async def update_prospect_research(
        self,
        seller_id: str,
        prospect_id: str,
        revision: int,
        status: ResearchStatusEnum,
        brief: BriefModel | None,
        error: str | None,
    ) -> bool:
        """Conditionally updates prospect research ONLY if revision matches."""
        pass

    # --- Briefings Cache ---
    @abstractmethod
    async def get_cached_entry(
        self, prospect_key: str, max_age_days: int = 30
    ) -> tuple[BriefModel, ResearchStatusEnum | None] | None:
        """Cached brief plus the research status stored with it (None for entries saved without one)."""
        pass

    async def get_cached_briefing(self, prospect_key: str, max_age_days: int = 30) -> BriefModel | None:
        entry = await self.get_cached_entry(prospect_key, max_age_days)
        return entry[0] if entry else None

    @abstractmethod
    async def save_cached_briefing(
        self, prospect_key: str, brief: BriefModel, status: ResearchStatusEnum | None = None
    ) -> None:
        pass

    # --- Research Jobs Queue ---
    @abstractmethod
    async def enqueue_research_jobs(self, seller_id: str, prospect_ids: list[str]) -> list[ResearchJobModel]:
        """Queue one job per prospect. Skips prospects with a live (unexpired) active job at the same
        revision; expired active jobs are marked failed and replaced."""
        pass

    @abstractmethod
    async def claim_research_job(
        self, worker_id: str, lease_seconds: int = 90, job_id: str | None = None
    ) -> ResearchJobModel | None:
        """Atomically move a QUEUED job (a specific one if job_id is given) to RUNNING with a lease.

        Without job_id, jobs still in retry backoff (notBefore in the future) are skipped."""
        pass

    @abstractmethod
    async def requeue_research_job(
        self, job_id: str, error: str, lease_seconds: int, delay_seconds: float = 0
    ) -> bool:
        """Return a RUNNING job to QUEUED for a retry (keeps its attempts count). The job stays live
        (not reclaimable by lease expiry) for lease_seconds, and a poller (claim without job_id) will not
        take it before delay_seconds pass. Returns False if it was no longer RUNNING."""
        pass

    @abstractmethod
    async def finish_research_job(
        self, job_id: str, status: ResearchStatusEnum, error: str | None = None
    ) -> None:
        pass

    @abstractmethod
    async def get_research_status(self, seller_id: str, prospect_id: str) -> ResearchJobModel | None:
        pass

    # --- Calls ---
    @abstractmethod
    async def get_active_call(self, seller_id: str) -> ActiveCallModel | None:
        pass

    @abstractmethod
    async def connect_call(self, seller_id: str, prospect_id: str) -> ActiveCallModel:
        pass

    @abstractmethod
    async def end_call(
        self, seller_id: str, outcome: CallOutcomeEnum, idempotency_key: str | None = None
    ) -> CompletedCallModel | None:
        pass

    @abstractmethod
    async def reset_call(self, seller_id: str, prospect_id: str) -> bool:
        pass

    @abstractmethod
    async def list_completed_calls(self, seller_id: str) -> list[CompletedCallModel]:
        """Completed calls for the seller, oldest first."""
        pass

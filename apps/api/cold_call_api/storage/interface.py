"""Abstract storage interface for Cold Call Conversion backend (Lane C)."""

from __future__ import annotations

from abc import ABC, abstractmethod
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


class StorageRepository(ABC):
    """Abstract interface defining all data operations required by the backend."""

    # --- Lists ---
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
    async def get_cached_briefing(self, prospect_key: str, max_age_days: int = 30) -> BriefModel | None:
        pass

    @abstractmethod
    async def save_cached_briefing(self, prospect_key: str, brief: BriefModel) -> None:
        pass

    # --- Research Jobs Queue ---
    @abstractmethod
    async def enqueue_research_jobs(self, seller_id: str, prospect_ids: list[str]) -> list[ResearchJobModel]:
        pass

    @abstractmethod
    async def claim_research_job(self, worker_id: str, lease_seconds: int = 90) -> ResearchJobModel | None:
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

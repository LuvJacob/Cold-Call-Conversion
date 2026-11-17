"""Research triggering and status routes (Lane C)."""

from __future__ import annotations

import asyncio
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from cold_call_api.auth import get_current_seller_id
from cold_call_api.models import (
    ResearchEnqueueInput,
    ResearchJobModel,
    ResearchStatusResponse,
)
from cold_call_api.services.worker import process_job
from cold_call_api.storage import get_repository
from cold_call_api.storage.interface import StorageRepository

router = APIRouter(prefix="/v1", tags=["Research"])


@router.post("/research", response_model=list[ResearchJobModel], status_code=status.HTTP_202_ACCEPTED)
async def enqueue_research(
    data: ResearchEnqueueInput,
    background_tasks: BackgroundTasks,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> list[ResearchJobModel]:
    """Enqueue background research for one or more prospects."""
    jobs = await repo.enqueue_research_jobs(seller_id, data.prospectIds)
    if not jobs:
        return []

    # Schedule asynchronous worker execution for each enqueued job
    for job in jobs:
        background_tasks.add_task(process_job, repo, job)

    return jobs


@router.get("/prospects/{prospect_id}/research", response_model=ResearchStatusResponse)
async def get_prospect_research_status(
    prospect_id: str,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ResearchStatusResponse:
    """Retrieve current research status, error, and completed brief for a prospect."""
    p = await repo.get_prospect(seller_id, prospect_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prospect {prospect_id} not found.",
        )
    return ResearchStatusResponse(
        prospectId=p.id,
        revision=p.revision,
        researchStatus=p.researchStatus,
        researchError=p.researchError,
        brief=p.brief,
    )

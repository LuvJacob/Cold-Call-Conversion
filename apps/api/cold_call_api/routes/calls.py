"""Call session and outcome management routes (Lane C)."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from cold_call_api.auth import get_current_seller_id
from cold_call_api.models import (
    ActiveCallModel,
    CompletedCallModel,
    ConnectCallInput,
    EndCallInput,
)
from cold_call_api.storage import get_repository
from cold_call_api.storage.interface import StorageRepository

router = APIRouter(prefix="/v1/calls", tags=["Calls"])


@router.get("/active", response_model=ActiveCallModel | None)
async def get_active_call(
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ActiveCallModel | None:
    """Retrieve the currently active call session if one exists."""
    return await repo.get_active_call(seller_id)


@router.post("", response_model=ActiveCallModel, status_code=status.HTTP_201_CREATED)
async def connect_call(
    data: ConnectCallInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ActiveCallModel:
    """Connect a call to a prospect. Only one call may be active at a time."""
    if not await repo.get_prospect(seller_id, data.prospectId):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prospect {data.prospectId} not found.",
        )
    try:
        return await repo.connect_call(seller_id, data.prospectId)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


@router.post("/end", response_model=CompletedCallModel)
async def end_call(
    data: EndCallInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CompletedCallModel:
    """End the active call and record the call outcome."""
    completed = await repo.end_call(seller_id, data.outcome, idempotency_key=idempotency_key)
    if not completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active call session to end.",
        )
    return completed


@router.post("/reset/{prospect_id}", status_code=status.HTTP_200_OK)
async def reset_prospect_call_status(
    prospect_id: str,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> dict[str, str]:
    """Reset a prospect's callStatus back to ready."""
    if not await repo.get_prospect(seller_id, prospect_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prospect {prospect_id} not found.",
        )
    ok = await repo.reset_call(seller_id, prospect_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not reset call status for prospect.",
        )
    return {"status": "ok"}

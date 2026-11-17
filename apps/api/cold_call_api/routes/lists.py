"""Calling lists and workspace routes (Lane C)."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from cold_call_api.auth import get_current_seller_id
from cold_call_api.models import (
    ListInput,
    ListModel,
    WorkspaceSummaryResponse,
)
from cold_call_api.storage import get_repository
from cold_call_api.storage.interface import StorageRepository

router = APIRouter(prefix="/v1", tags=["Lists & Workspace"])


@router.get("/workspace", response_model=WorkspaceSummaryResponse)
async def get_workspace(
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> WorkspaceSummaryResponse:
    """Fetch complete workspace state for the authenticated seller."""
    lists = await repo.get_lists(seller_id)
    prospects = await repo.get_prospects(seller_id)
    active_call = await repo.get_active_call(seller_id)
    return WorkspaceSummaryResponse(
        version=1,
        lists=lists,
        prospects=prospects,
        activeCall=active_call,
        calls=[],
    )


@router.get("/lists", response_model=list[ListModel])
async def list_calling_lists(
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> list[ListModel]:
    """Retrieve all calling lists for the seller."""
    return await repo.get_lists(seller_id)


@router.post("/lists", response_model=ListModel, status_code=status.HTTP_201_CREATED)
async def create_calling_list(
    data: ListInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ListModel:
    """Create a new calling list."""
    current_lists = await repo.get_lists(seller_id)
    if len(current_lists) >= 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum limit of 50 lists reached.",
        )
    return await repo.create_list(seller_id, data.name)


@router.patch("/lists/{list_id}", response_model=ListModel)
async def rename_calling_list(
    list_id: str,
    data: ListInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ListModel:
    """Rename an existing calling list."""
    updated = await repo.update_list(seller_id, list_id, data.name)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found.",
        )
    return updated


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calling_list(
    list_id: str,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> None:
    """Delete a calling list and its prospects."""
    lists = await repo.get_lists(seller_id)
    if len(lists) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the only remaining calling list.",
        )
    deleted = await repo.delete_list(seller_id, list_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="List not found or has an active call.",
        )

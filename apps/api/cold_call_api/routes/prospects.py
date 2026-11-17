"""Prospects and CSV import routes (Lane C)."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from cold_call_api.auth import get_current_seller_id
from cold_call_api.csv_parser import MAX_CSV_BYTES, parse_prospect_csv
from cold_call_api.models import (
    CsvImportResponse,
    CsvImportRowError,
    MoveProspectInput,
    ProspectInput,
    ProspectModel,
    ProspectUpdateInput,
)
from cold_call_api.storage import get_repository
from cold_call_api.storage.interface import StorageRepository

router = APIRouter(prefix="/v1", tags=["Prospects"])


async def _require_prospect(repo: StorageRepository, seller_id: str, prospect_id: str) -> None:
    """404 unless the prospect exists for this seller (same answer for other sellers' ids)."""
    if not await repo.get_prospect(seller_id, prospect_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prospect {prospect_id} not found.",
        )


@router.get("/lists/{list_id}/prospects", response_model=list[ProspectModel])
async def get_list_prospects(
    list_id: str,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> list[ProspectModel]:
    """Get all prospects belonging to a calling list."""
    l = await repo.get_list(seller_id, list_id)
    if not l:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found.",
        )
    return await repo.get_prospects(seller_id, list_id)


@router.post("/lists/{list_id}/prospects", response_model=list[ProspectModel], status_code=status.HTTP_201_CREATED)
async def add_prospects_to_list(
    list_id: str,
    inputs: list[ProspectInput] | ProspectInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> list[ProspectModel]:
    """Add one or more prospects to a list."""
    l = await repo.get_list(seller_id, list_id)
    if not l:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found.",
        )
    input_list = [inputs] if isinstance(inputs, ProspectInput) else inputs
    if not input_list:
        return []
    created, _ = await repo.create_prospects(seller_id, list_id, input_list)
    return created


@router.post("/lists/{list_id}/import", response_model=CsvImportResponse)
async def import_prospects_csv(
    list_id: str,
    file: Annotated[UploadFile, File()],
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> CsvImportResponse:
    """Upload and validate a CSV calling list file."""
    l = await repo.get_list(seller_id, list_id)
    if not l:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found.",
        )
    content = await file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Choose a CSV smaller than 1 MB.",
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file encoding. Please upload a UTF-8 CSV.",
            ) from err

    result = parse_prospect_csv(text)
    if (result.errors or result.row_errors) and not result.rows:
        messages = list(result.errors) + [f"Row {n}: {m}" for n, m in result.row_errors]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(messages),
        )

    created: list[ProspectModel] = []
    duplicates_skipped = 0
    if result.rows:
        created, duplicates_skipped = await repo.create_prospects(seller_id, list_id, result.rows)

    row_errors = [CsvImportRowError(row=n, message=m) for n, m in result.row_errors]
    return CsvImportResponse(
        imported=created,
        rejectedRows=row_errors,
        duplicatesSkipped=duplicates_skipped,
    )


@router.patch("/prospects/{prospect_id}", response_model=ProspectModel)
async def update_prospect(
    prospect_id: str,
    data: ProspectUpdateInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> ProspectModel:
    """Edit prospect details (bumps revision, clears prior brief)."""
    await _require_prospect(repo, seller_id, prospect_id)
    updated = await repo.update_prospect(seller_id, prospect_id, data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prospect cannot be modified while on an active call.",
        )
    return updated


@router.delete("/prospects/{prospect_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prospect(
    prospect_id: str,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> None:
    """Delete a prospect."""
    await _require_prospect(repo, seller_id, prospect_id)
    deleted = await repo.delete_prospect(seller_id, prospect_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prospect cannot be deleted while on an active call.",
        )


@router.post("/prospects/{prospect_id}/move", status_code=status.HTTP_200_OK)
async def move_prospect(
    prospect_id: str,
    data: MoveProspectInput,
    seller_id: Annotated[str, Depends(get_current_seller_id)],
    repo: Annotated[StorageRepository, Depends(get_repository)],
) -> dict[str, str]:
    """Reorder a prospect within its list."""
    await _require_prospect(repo, seller_id, prospect_id)
    moved = await repo.move_prospect(seller_id, prospect_id, data.direction)
    if not moved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not move prospect in the specified direction.",
        )
    return {"status": "ok"}

"""Prospects CRUD and mutation tests (Lane C)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_prospect_crud_and_deduplication(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    # Create list
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Alpha List"})
    list_id = res.json()["id"]

    # Add prospects
    prospects_payload = [
        {"name": "Maya Chen", "company": "Northstar Logistics", "role": "VP IT", "phone": "123", "notes": "note1"},
        {"name": "Jordan Ellis", "company": "Meridian Consulting", "role": "Director IT", "phone": "", "notes": ""},
    ]
    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json=prospects_payload,
    )
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 2
    p1_id = created[0]["id"]
    assert created[0]["revision"] == 0

    # Adding duplicate in same list should skip duplicate
    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json=[{"name": "Maya Chen", "company": "Northstar Logistics", "role": "VP IT", "phone": "999", "notes": "new"}],
    )
    assert res.status_code == 201
    assert len(res.json()) == 0  # 0 new created

    # Update prospect - bumps revision and clears brief
    res = await client.patch(
        f"/v1/prospects/{p1_id}",
        headers=auth_headers_seller1,
        json={"role": "Senior VP IT", "notes": "Updated note"},
    )
    assert res.status_code == 200
    updated = res.json()
    assert updated["role"] == "Senior VP IT"
    assert updated["revision"] == 1
    assert updated["researchStatus"] == "not-started"

    # Move prospect
    res = await client.post(
        f"/v1/prospects/{p1_id}/move",
        headers=auth_headers_seller1,
        json={"direction": 1},
    )
    assert res.status_code == 200

    # Delete prospect
    res = await client.delete(f"/v1/prospects/{p1_id}", headers=auth_headers_seller1)
    assert res.status_code == 204

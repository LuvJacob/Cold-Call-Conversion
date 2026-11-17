"""BOLA (Broken Object Level Authorization) and cross-seller isolation security tests (Lane C)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_seller_isolation_lists_and_prospects(
    client: AsyncClient,
    auth_headers_seller1: dict[str, str],
    auth_headers_seller2: dict[str, str],
) -> None:
    # Seller 1 creates list and prospect
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Seller 1 Private List"})
    assert res.status_code == 201
    s1_list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{s1_list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Confidential Prospect", "company": "Secret Corp", "role": "CEO", "phone": "", "notes": ""},
    )
    assert res.status_code == 201
    s1_prospect_id = res.json()[0]["id"]

    # Seller 2 listing should be empty
    res = await client.get("/v1/lists", headers=auth_headers_seller2)
    assert res.status_code == 200
    assert res.json() == []

    # Seller 2 trying to get Seller 1's prospects returns 404
    res = await client.get(f"/v1/lists/{s1_list_id}/prospects", headers=auth_headers_seller2)
    assert res.status_code == 404

    # Seller 2 trying to update Seller 1's prospect returns 404
    res = await client.patch(
        f"/v1/prospects/{s1_prospect_id}",
        headers=auth_headers_seller2,
        json={"name": "Hacked Name"},
    )
    assert res.status_code == 404

    # Seller 2 trying to delete Seller 1's list returns 404
    res = await client.delete(f"/v1/lists/{s1_list_id}", headers=auth_headers_seller2)
    assert res.status_code == 404

    # Verify Seller 1's data remained untouched
    res = await client.get(f"/v1/lists/{s1_list_id}/prospects", headers=auth_headers_seller1)
    assert res.status_code == 200
    assert res.json()[0]["name"] == "Confidential Prospect"

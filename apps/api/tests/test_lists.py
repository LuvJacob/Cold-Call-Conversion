"""List CRUD and workspace tests (Lane C)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_get_lists(client: AsyncClient, auth_headers_seller1: dict[str, str]) -> None:
    # Initially empty
    res = await client.get("/v1/lists", headers=auth_headers_seller1)
    assert res.status_code == 200
    assert res.json() == []

    # Create a list
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Tech Leads"})
    assert res.status_code == 201
    created = res.json()
    assert created["name"] == "Tech Leads"
    assert created["sellerId"] == "seller-1"
    list_id = created["id"]

    # Retrieve lists
    res = await client.get("/v1/lists", headers=auth_headers_seller1)
    assert res.status_code == 200
    lists = res.json()
    assert len(lists) == 1
    assert lists[0]["id"] == list_id

    # Rename list
    res = await client.patch(f"/v1/lists/{list_id}", headers=auth_headers_seller1, json={"name": "Enterprise Leads"})
    assert res.status_code == 200
    assert res.json()["name"] == "Enterprise Leads"


@pytest.mark.asyncio
async def test_cannot_delete_only_remaining_list(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Only List"})
    list_id = res.json()["id"]

    # Deleting only list should fail
    res = await client.delete(f"/v1/lists/{list_id}", headers=auth_headers_seller1)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_delete_list_when_multiple(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    res1 = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "List 1"})
    res2 = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "List 2"})
    id1 = res1.json()["id"]
    id2 = res2.json()["id"]

    res = await client.delete(f"/v1/lists/{id1}", headers=auth_headers_seller1)
    assert res.status_code == 204

    # Verify only list 2 remains
    res = await client.get("/v1/lists", headers=auth_headers_seller1)
    lists = res.json()
    assert len(lists) == 1
    assert lists[0]["id"] == id2

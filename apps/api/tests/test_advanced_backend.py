"""Advanced backend edge-cases and worker loop tests (Lane C)."""

import asyncio
import pytest
from httpx import AsyncClient
from cold_call_api.services.worker import run_worker_loop
from cold_call_api.storage import get_repository


@pytest.mark.asyncio
async def test_workspace_summary_hydration(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    # Create list
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Workspace List"})
    list_id = res.json()["id"]

    # Create prospect
    await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Alex Morgan", "company": "Atlas Manufacturing", "role": "Head of Infra", "phone": "555", "notes": ""},
    )

    # Fetch workspace
    res = await client.get("/v1/workspace", headers=auth_headers_seller1)
    assert res.status_code == 200
    ws = res.json()
    assert ws["version"] == 1
    assert len(ws["lists"]) == 1
    assert len(ws["prospects"]) == 1
    assert ws["activeCall"] is None


@pytest.mark.asyncio
async def test_prospect_move_boundary_conditions(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Move List"})
    list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json=[
            {"name": "P1", "company": "C1", "role": "R1", "phone": "", "notes": ""},
            {"name": "P2", "company": "C2", "role": "R2", "phone": "", "notes": ""},
        ],
    )
    p1_id = res.json()[0]["id"]
    p2_id = res.json()[1]["id"]

    # Moving first item up (-1) should fail
    res = await client.post(f"/v1/prospects/{p1_id}/move", headers=auth_headers_seller1, json={"direction": -1})
    assert res.status_code == 400

    # Moving second item down (+1) should fail
    res = await client.post(f"/v1/prospects/{p2_id}/move", headers=auth_headers_seller1, json={"direction": 1})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_worker_loop_once(client: AsyncClient, auth_headers_seller1: dict[str, str]) -> None:
    repo = get_repository()

    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Worker List"})
    list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Harbor Prospect", "company": "Harbor Financial", "role": "CTO", "phone": "", "notes": ""},
    )
    pid = res.json()[0]["id"]

    # Enqueue job
    await client.post("/v1/research", headers=auth_headers_seller1, json={"prospectIds": [pid]})

    # Run worker loop once
    await run_worker_loop(repo, once=True)

    # Verify prospect research status updated
    res = await client.get(f"/v1/prospects/{pid}/research", headers=auth_headers_seller1)
    assert res.json()["researchStatus"] in ("ready", "partial")


@pytest.mark.asyncio
async def test_openapi_schema_endpoint(client: AsyncClient) -> None:
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert "paths" in schema
    assert "/healthz" in schema["paths"]
    assert "/v1/lists" in schema["paths"]
    assert "/v1/research" in schema["paths"]
    assert "/v1/calls" in schema["paths"]

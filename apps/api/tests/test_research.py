"""Research integration and worker tests (Lane C)."""

import pytest
from httpx import AsyncClient
from cold_call_api.services.worker import process_job
from cold_call_api.storage import get_repository


@pytest.mark.asyncio
async def test_research_execution_and_caching(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    repo = get_repository()

    # Create list and prospect with fixture match
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Research List"})
    list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Maya Chen", "company": "Northstar Logistics", "role": "VP IT", "phone": "123", "notes": ""},
    )
    prospect_id = res.json()[0]["id"]

    # Enqueue research
    res = await client.post(
        "/v1/research",
        headers=auth_headers_seller1,
        json={"prospectIds": [prospect_id]},
    )
    assert res.status_code == 202
    jobs = res.json()
    assert len(jobs) == 1
    job_id = jobs[0]["id"]

    # Read status
    res = await client.get(f"/v1/prospects/{prospect_id}/research", headers=auth_headers_seller1)
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["researchStatus"] in ("running", "ready", "partial")

    # Claim and process job directly if not completed
    job = await repo.claim_research_job("test-worker")
    if job:
        await process_job(repo, job)

    # Read updated status and brief
    res = await client.get(f"/v1/prospects/{prospect_id}/research", headers=auth_headers_seller1)
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["researchStatus"] in ("ready", "partial")
    brief = status_data["brief"]
    assert brief is not None
    assert brief["mode"] == "demo"
    assert "summary" in brief
    assert len(brief["facts"]) > 0
    assert len(brief["sources"]) > 0


@pytest.mark.asyncio
async def test_stale_revision_protection(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    repo = get_repository()

    # Create list and prospect
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Stale List"})
    list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Jordan Ellis", "company": "Meridian Consulting", "role": "Director IT", "phone": "", "notes": ""},
    )
    prospect_id = res.json()[0]["id"]

    # Enqueue job at revision 0
    res = await client.post(
        "/v1/research",
        headers=auth_headers_seller1,
        json={"prospectIds": [prospect_id]},
    )
    job_id = res.json()[0]["id"]

    # User immediately edits the prospect, bumping revision to 1
    res = await client.patch(
        f"/v1/prospects/{prospect_id}",
        headers=auth_headers_seller1,
        json={"role": "Chief Information Officer"},
    )
    assert res.json()["revision"] == 1

    # Worker executes the old job (for revision 0)
    job = await repo.claim_research_job("test-worker")
    if job:
        await process_job(repo, job)

    # Prospect should NOT have the old brief applied and revision stays 1 with status not-started
    res = await client.get(f"/v1/prospects/{prospect_id}/research", headers=auth_headers_seller1)
    status_data = res.json()
    assert status_data["revision"] == 1
    assert status_data["researchStatus"] == "not-started"
    assert status_data["brief"] is None

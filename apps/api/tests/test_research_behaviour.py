"""Research enqueue idempotency and honest fallback briefings (Lane C)."""

import pytest
from httpx import AsyncClient

from cold_call_api.services.worker import run_worker_loop
from cold_call_api.storage import get_repository

H = {"X-Seller-ID": "seller-1"}


async def _prospect(client: AsyncClient, name: str, company: str) -> str:
    list_id = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    res = await client.post(
        f"/v1/lists/{list_id}/prospects", headers=H, json={"name": name, "company": company, "role": "VP"}
    )
    return res.json()[0]["id"]


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_while_job_in_flight(client: AsyncClient) -> None:
    # Use the repository directly: the HTTP route runs the job as a background task.
    pid = await _prospect(client, "Dana Reyes", "Northwind Logistics Sample Inc")
    repo = get_repository()
    first = await repo.enqueue_research_jobs("seller-1", [pid])
    second = await repo.enqueue_research_jobs("seller-1", [pid, pid])
    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_enqueue_allowed_again_after_edit_bumps_revision(client: AsyncClient) -> None:
    pid = await _prospect(client, "Dana Reyes", "Northwind Logistics Sample Inc")
    repo = get_repository()
    assert len(await repo.enqueue_research_jobs("seller-1", [pid])) == 1
    await client.patch(f"/v1/prospects/{pid}", headers=H, json={"role": "CIO"})
    assert len(await repo.enqueue_research_jobs("seller-1", [pid])) == 1


@pytest.mark.asyncio
async def test_enqueue_allowed_again_after_job_finishes(client: AsyncClient) -> None:
    pid = await _prospect(client, "Dana Reyes", "Northwind Logistics Sample Inc")
    repo = get_repository()
    await repo.enqueue_research_jobs("seller-1", [pid])
    await run_worker_loop(repo, once=True)
    assert len(await repo.enqueue_research_jobs("seller-1", [pid])) == 1


@pytest.mark.asyncio
async def test_enqueue_ignores_other_sellers_prospects(client: AsyncClient) -> None:
    pid = await _prospect(client, "Dana Reyes", "Northwind Logistics Sample Inc")
    res = await client.post("/v1/research", headers={"X-Seller-ID": "seller-2"}, json={"prospectIds": [pid]})
    assert res.json() == []


@pytest.mark.asyncio
async def test_unknown_prospect_gets_no_invented_facts(client: AsyncClient) -> None:
    pid = await _prospect(client, "Jane Smith", "Zeta Corp")
    await client.post("/v1/research", headers=H, json={"prospectIds": [pid]})
    await run_worker_loop(get_repository(), once=True)

    data = (await client.get(f"/v1/prospects/{pid}/research", headers=H)).json()
    assert data["researchStatus"] == "partial"
    brief = data["brief"]
    assert brief["facts"] == []
    assert brief["sources"] == []
    assert any("No live research providers" in u for u in brief["uncertainty"])
    assert "regional and national" not in str(brief)


def test_mongodb_backend_without_uri_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from cold_call_api import storage
    from cold_call_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "mongodb")
    monkeypatch.setattr(settings, "mongodb_uri", "")
    monkeypatch.setattr(storage, "_repo_instance", None)
    with pytest.raises(RuntimeError, match="MONGODB_URI"):
        storage.get_repository()

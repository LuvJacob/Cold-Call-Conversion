"""MongoDB storage tests against a REAL database (Lane C).

Skipped unless the MONGO_URL environment variable is set, so normal test runs stay offline:

    docker compose up -d mongo
    export MONGO_URL="mongodb://<user>:<password>@127.0.0.1:27017/?authSource=admin"
    uv run --extra dev --extra mongodb pytest tests/test_mongo_storage.py -v

Each test module run uses its own throwaway database (dropped afterwards), never
the application's database.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

MONGO_URL = os.getenv("MONGO_URL", "")

pytestmark = pytest.mark.skipif(not MONGO_URL, reason="MONGO_URL not set; Mongo storage tests need a real database")

pytest.importorskip("pymongo")

from cold_call_api.main import app  # noqa: E402
from cold_call_api.models import (  # noqa: E402
    BriefModel,
    CallOutcomeEnum,
    CallStatusEnum,
    ProspectInput,
    ProspectUpdateInput,
    ResearchStatusEnum,
)
from cold_call_api.storage import set_repository  # noqa: E402
from cold_call_api.storage.mongodb import MongoStorageRepository  # noqa: E402

S1 = "seller-1"
S2 = "seller-2"


def _prospect(i: int = 1, company: str = "Acme") -> ProspectInput:
    return ProspectInput(name=f"Person {i}", company=company, role="VP", phone="", notes="")


def _brief(summary: str = "s") -> BriefModel:
    return BriefModel(preparedAt="2026-01-01T00:00:00Z", summary=summary)


@pytest.fixture(scope="module")
def db_name() -> Iterator[str]:
    name = f"cc_test_{uuid.uuid4().hex[:10]}"
    yield name
    from pymongo import MongoClient

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    client.drop_database(name)
    client.close()


@pytest.fixture
def repo(db_name: str) -> Iterator[MongoStorageRepository]:
    r = MongoStorageRepository(MONGO_URL, db_name)
    for coll in ("lists", "prospects", "brief_cache", "research_jobs", "active_calls", "completed_calls"):
        r.db[coll].delete_many({})
    set_repository(r)
    yield r
    r.client.close()


@pytest.fixture
async def mclient(repo: MongoStorageRepository) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _list_and_prospects(repo: MongoStorageRepository, n: int = 2, seller: str = S1):
    lst = await repo.create_list(seller, "L")
    created, dups = await repo.create_prospects(seller, lst.id, [_prospect(i) for i in range(1, n + 1)])
    assert dups == 0
    return lst, created


# --- Lists / prospects -------------------------------------------------------------------


async def test_indexes_created_and_idempotent(repo: MongoStorageRepository, db_name: str) -> None:
    MongoStorageRepository(MONGO_URL, db_name).client.close()  # second init must not fail
    names = set(repo.db["research_jobs"].index_information())
    assert "one_active_job_per_revision" in names


async def test_list_crud_and_seller_isolation(repo: MongoStorageRepository) -> None:
    a = await repo.create_list(S1, "  Mine  ")
    assert a.name == "Mine"
    assert [x.id for x in await repo.get_lists(S1)] == [a.id]
    assert await repo.get_lists(S2) == []
    assert await repo.get_list(S2, a.id) is None
    assert await repo.update_list(S2, a.id, "hijack") is None
    renamed = await repo.update_list(S1, a.id, "Renamed")
    assert renamed is not None and renamed.name == "Renamed"
    assert await repo.delete_list(S2, a.id) is False
    assert await repo.delete_list(S1, a.id) is True
    assert await repo.get_list(S1, a.id) is None


async def test_ensure_default_list_is_idempotent_and_concurrency_safe(repo: MongoStorageRepository) -> None:
    results = await asyncio.gather(*[repo.ensure_default_list("fresh-seller") for _ in range(10)])
    assert len({r.id for r in results}) == 1
    assert len(await repo.get_lists("fresh-seller")) == 1
    existing = await repo.create_list(S1, "Existing")
    assert (await repo.ensure_default_list(S1)).id == existing.id


async def test_create_prospects_positions_and_duplicates(repo: MongoStorageRepository) -> None:
    lst = await repo.create_list(S1, "L")
    created, dups = await repo.create_prospects(S1, lst.id, [_prospect(1), _prospect(2), _prospect(1)])
    assert [p.position for p in created] == [0, 1]
    assert dups == 1
    more, dups2 = await repo.create_prospects(S1, lst.id, [_prospect(1), _prospect(3)])
    assert [p.name for p in more] == ["Person 3"] and dups2 == 1 and more[0].position == 2
    with pytest.raises(ValueError):
        await repo.create_prospects(S2, lst.id, [_prospect(9)])  # not owned
    assert [p.name for p in await repo.get_prospects(S1, lst.id)] == ["Person 1", "Person 2", "Person 3"]


async def test_update_prospect_bumps_revision_resets_research(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    await repo.update_prospect_research(S1, p.id, p.revision, ResearchStatusEnum.READY, _brief(), None)
    updated = await repo.update_prospect(S1, p.id, ProspectUpdateInput(role="CIO"))
    assert updated is not None
    assert (updated.revision, updated.role, updated.brief, updated.researchStatus) == (
        p.revision + 1, "CIO", None, ResearchStatusEnum.NOT_STARTED,
    )
    assert await repo.update_prospect(S2, p.id, ProspectUpdateInput(role="x")) is None
    assert await repo.update_prospect(S1, "missing", ProspectUpdateInput(role="x")) is None


async def test_concurrent_edits_get_distinct_revisions(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    outs = await asyncio.gather(
        *[repo.update_prospect(S1, p.id, ProspectUpdateInput(notes=f"n{i}")) for i in range(8)]
    )
    assert sorted(o.revision for o in outs if o) == list(range(1, 9))


async def test_move_and_delete_prospect(repo: MongoStorageRepository) -> None:
    lst, (a, b) = await _list_and_prospects(repo)
    assert await repo.move_prospect(S1, a.id, -1) is False
    assert await repo.move_prospect(S1, b.id, 1) is False
    assert await repo.move_prospect(S2, a.id, 1) is False
    assert await repo.move_prospect(S1, a.id, 1) is True
    assert [p.id for p in await repo.get_prospects(S1, lst.id)] == [b.id, a.id]
    assert await repo.delete_prospect(S2, a.id) is False
    assert await repo.delete_prospect(S1, a.id) is True
    assert await repo.get_prospect(S1, a.id) is None


async def test_delete_list_removes_its_prospects(repo: MongoStorageRepository) -> None:
    lst, (a, _) = await _list_and_prospects(repo)
    assert await repo.delete_list(S1, lst.id) is True
    assert await repo.get_prospect(S1, a.id) is None


# --- Research ------------------------------------------------------------------------------


async def test_update_prospect_research_stale_guard(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    assert await repo.update_prospect_research(S1, p.id, p.revision + 5, ResearchStatusEnum.READY, _brief(), None) is False
    assert await repo.update_prospect_research(S2, p.id, p.revision, ResearchStatusEnum.READY, _brief(), None) is False
    assert await repo.update_prospect_research(S1, p.id, p.revision, ResearchStatusEnum.READY, _brief("x"), None) is True
    # identical rewrite must still count as applied (matched, not modified)
    assert await repo.update_prospect_research(S1, p.id, p.revision, ResearchStatusEnum.READY, _brief("x"), None) is True
    got = await repo.get_prospect(S1, p.id)
    assert got is not None and got.brief is not None and got.brief.summary == "x"


async def test_brief_cache_roundtrip_and_expiry(repo: MongoStorageRepository) -> None:
    assert await repo.get_cached_briefing("k") is None
    await repo.save_cached_briefing("k", _brief("cached"))
    got = await repo.get_cached_briefing("k")
    assert got is not None and got.summary == "cached"
    await repo.save_cached_briefing("k", _brief("newer"))  # upsert, no duplicate-key error
    got = await repo.get_cached_briefing("k")
    assert got is not None and got.summary == "newer"
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    repo.db["brief_cache"].update_one({"prospectKey": "k"}, {"$set": {"savedAt": old}})
    assert await repo.get_cached_briefing("k", max_age_days=30) is None
    assert repo.db["brief_cache"].count_documents({"prospectKey": "k"}) == 0


async def test_enqueue_claim_finish_lifecycle(repo: MongoStorageRepository) -> None:
    _, (p, q) = await _list_and_prospects(repo)
    jobs = await repo.enqueue_research_jobs(S1, [p.id, q.id, "missing"])
    assert len(jobs) == 2 and all(j.status == ResearchStatusEnum.QUEUED for j in jobs)
    assert (await repo.get_prospect(S1, p.id)).researchStatus == ResearchStatusEnum.RUNNING  # type: ignore[union-attr]

    claimed = await repo.claim_research_job("w1", job_id=jobs[0].id)
    assert claimed is not None and claimed.id == jobs[0].id
    assert claimed.status == ResearchStatusEnum.RUNNING and claimed.attempts == 1 and claimed.claimedBy == "w1"
    assert await repo.claim_research_job("w2", job_id=jobs[0].id) is None  # already claimed
    other = await repo.claim_research_job("w2")  # any queued job
    assert other is not None and other.id == jobs[1].id
    assert await repo.claim_research_job("w3") is None

    await repo.finish_research_job(jobs[0].id, ResearchStatusEnum.READY)
    latest = await repo.get_research_status(S1, p.id)
    assert latest is not None and latest.status == ResearchStatusEnum.READY and latest.leaseExpiresAt is None
    assert await repo.get_research_status(S2, p.id) is None


async def test_enqueue_is_idempotent_and_race_safe(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    batches = await asyncio.gather(*[repo.enqueue_research_jobs(S1, [p.id]) for _ in range(10)])
    assert sum(len(b) for b in batches) == 1
    assert repo.db["research_jobs"].count_documents({"prospectId": p.id}) == 1
    # after the job finishes, the same revision can be researched again
    only = next(b[0] for b in batches if b)
    await repo.finish_research_job(only.id, ResearchStatusEnum.READY)
    assert len(await repo.enqueue_research_jobs(S1, [p.id])) == 1


async def test_enqueue_allowed_after_revision_bump_and_replaces_expired_job(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    first = (await repo.enqueue_research_jobs(S1, [p.id]))[0]
    await repo.update_prospect(S1, p.id, ProspectUpdateInput(role="CIO"))
    assert len(await repo.enqueue_research_jobs(S1, [p.id])) == 1  # new revision, new job
    # expire the (new) job's lease: it must be failed and replaced
    cur = await repo.get_prospect(S1, p.id)
    assert cur is not None
    repo.db["research_jobs"].update_many(
        {"prospectId": p.id, "revision": cur.revision, "active": True},
        {"$set": {"createdAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "leaseExpiresAt": None}},
    )
    replacement = await repo.enqueue_research_jobs(S1, [p.id])
    assert len(replacement) == 1
    states = [d["status"] for d in repo.db["research_jobs"].find({"prospectId": p.id, "revision": cur.revision})]
    assert sorted(states) == ["failed", "queued"]
    assert first.id != replacement[0].id


async def test_enqueue_ignores_other_sellers_and_active_call_prospect(repo: MongoStorageRepository) -> None:
    _, (p, q) = await _list_and_prospects(repo)
    assert await repo.enqueue_research_jobs(S2, [p.id]) == []
    await repo.connect_call(S1, p.id)
    assert await repo.enqueue_research_jobs(S1, [p.id]) == []
    assert len(await repo.enqueue_research_jobs(S1, [q.id])) == 1


# --- Calls ---------------------------------------------------------------------------------


async def test_call_lifecycle(repo: MongoStorageRepository) -> None:
    _, (p, q) = await _list_and_prospects(repo)
    assert await repo.get_active_call(S1) is None
    call = await repo.connect_call(S1, p.id)
    assert call.prospectId == p.id
    active = await repo.get_active_call(S1)
    assert active is not None and active.prospectId == p.id
    assert await repo.get_active_call(S2) is None

    with pytest.raises(ValueError):
        await repo.connect_call(S1, q.id)  # one active call at a time
    with pytest.raises(ValueError):
        await repo.connect_call(S2, p.id)  # not their prospect
    assert await repo.update_prospect(S1, p.id, ProspectUpdateInput(role="x")) is None
    assert await repo.delete_prospect(S1, p.id) is False
    assert await repo.reset_call(S1, p.id) is False  # cannot reset while on the call

    done = await repo.end_call(S1, CallOutcomeEnum.FOLLOW_UP, idempotency_key="k1")
    assert done is not None and done.outcome == CallOutcomeEnum.FOLLOW_UP and done.prospectId == p.id
    assert await repo.get_active_call(S1) is None
    after = await repo.get_prospect(S1, p.id)
    assert after is not None and (after.callStatus, after.outcome) == (CallStatusEnum.CALLED, CallOutcomeEnum.FOLLOW_UP)

    replay = await repo.end_call(S1, CallOutcomeEnum.FOLLOW_UP, idempotency_key="k1")
    assert replay is not None and replay.id == done.id
    assert await repo.end_call(S1, CallOutcomeEnum.COMPLETED) is None
    assert await repo.end_call(S1, CallOutcomeEnum.COMPLETED, idempotency_key="unknown") is None
    assert [c.id for c in await repo.list_completed_calls(S1)] == [done.id]
    assert await repo.list_completed_calls(S2) == []

    assert await repo.reset_call(S1, p.id) is True
    assert await repo.reset_call(S1, p.id) is True  # already ready: still success
    assert await repo.reset_call(S2, p.id) is False
    assert await repo.reset_call(S1, "missing") is False
    back = await repo.get_prospect(S1, p.id)
    assert back is not None and (back.callStatus, back.outcome) == (CallStatusEnum.READY, None)


async def test_concurrent_connect_allows_exactly_one(repo: MongoStorageRepository) -> None:
    _, (p, q) = await _list_and_prospects(repo)
    results = await asyncio.gather(
        *[repo.connect_call(S1, pid) for pid in (p.id, q.id) * 4], return_exceptions=True
    )
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1
    assert all(isinstance(r, ValueError) for r in results if isinstance(r, Exception))
    assert repo.db["active_calls"].count_documents({"sellerId": S1}) == 1


async def test_concurrent_end_records_exactly_one_completed_call(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    await repo.connect_call(S1, p.id)
    results = await asyncio.gather(*[repo.end_call(S1, CallOutcomeEnum.COMPLETED) for _ in range(8)])
    assert sum(1 for r in results if r is not None) == 1
    assert repo.db["completed_calls"].count_documents({"sellerId": S1}) == 1


async def test_concurrent_end_with_same_idempotency_key_is_one_call(repo: MongoStorageRepository) -> None:
    _, (p, _) = await _list_and_prospects(repo)
    await repo.connect_call(S1, p.id)
    results = await asyncio.gather(*[repo.end_call(S1, CallOutcomeEnum.COMPLETED, idempotency_key="same") for _ in range(8)])
    ids = {r.id for r in results if r is not None}
    assert len(ids) == 1
    assert repo.db["completed_calls"].count_documents({"sellerId": S1}) == 1


# --- Through the HTTP API on the Mongo backend ------------------------------------------------


async def test_http_flow_on_mongo(mclient: AsyncClient) -> None:
    h = {"X-Seller-ID": "http-seller"}
    lid = (await mclient.post("/v1/lists", headers=h, json={"name": "L"})).json()["id"]
    csv = b"name,company,role\nDana Reyes,Northwind Logistics Sample Inc,VP Ops\nJane Smith,Zeta Corp,CIO\n"
    res = await mclient.post(f"/v1/lists/{lid}/import", headers=h, files={"file": ("l.csv", csv, "text/csv")})
    assert res.status_code == 200 and len(res.json()["imported"]) == 2
    ids = {p["name"]: p["id"] for p in res.json()["imported"]}

    res = await mclient.post("/v1/research", headers=h, json={"prospectIds": list(ids.values())})
    assert res.status_code == 202 and len(res.json()) == 2

    # background tasks run before the response returns under ASGITransport
    data = (await mclient.get(f"/v1/prospects/{ids['Dana Reyes']}/research", headers=h)).json()
    assert data["researchStatus"] in ("ready", "partial") and data["brief"]["facts"]
    jane = (await mclient.get(f"/v1/prospects/{ids['Jane Smith']}/research", headers=h)).json()
    assert jane["brief"]["facts"] == []

    dana = ids["Dana Reyes"]
    assert (await mclient.post("/v1/calls", headers=h, json={"prospectId": dana})).status_code == 201
    assert (await mclient.post("/v1/calls", headers=h, json={"prospectId": ids["Jane Smith"]})).status_code in (400, 409)
    end = await mclient.post("/v1/calls/end", headers={**h, "Idempotency-Key": "abc"}, json={"outcome": "completed"})
    assert end.status_code == 200
    ws = (await mclient.get("/v1/workspace", headers=h)).json()
    assert len(ws["calls"]) == 1
    assert (await mclient.post(f"/v1/calls/reset/{dana}", headers=h)).status_code == 200
    other = await mclient.get(f"/v1/lists/{lid}/prospects", headers={"X-Seller-ID": "intruder"})
    assert other.status_code == 404

"""Tests for stuck-job recovery, fixture matching, caching, and auth safety (memory repo)."""

from datetime import datetime, timedelta, timezone

import pytest

from cold_call_api.config import settings
from cold_call_api.main import app, lifespan
from cold_call_api.models import ProspectInput, ProspectUpdateInput, ResearchStatusEnum
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"


async def _repo_with(name="Dana Reyes", company="Northwind Logistics Sample Inc", notes=""):
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(
        S, lst.id, [ProspectInput(name=name, company=company, role="VP", phone="1", notes=notes)]
    )
    return repo, created[0]


def _age(repo, job_id, seconds, lease=True):
    j = repo._jobs[job_id]
    past = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    repo._jobs[job_id] = j.model_copy(
        update={"leaseExpiresAt": past if lease else None, "createdAt": past}
    )


async def test_live_job_blocks_reenqueue_but_expired_job_is_replaced() -> None:
    repo, p = await _repo_with()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    assert await repo.enqueue_research_jobs(S, [p.id]) == []

    _age(repo, job.id, settings.research_lease_seconds + 5, lease=False)  # queued, never claimed
    (job2,) = await repo.enqueue_research_jobs(S, [p.id])
    assert job2.id != job.id
    assert repo._jobs[job.id].status == ResearchStatusEnum.FAILED

    claimed = await repo.claim_research_job("w", lease_seconds=90, job_id=job2.id)
    assert claimed and claimed.leaseExpiresAt
    assert await repo.enqueue_research_jobs(S, [p.id]) == []  # lease still live
    _age(repo, job2.id, 5)  # lease expired (crashed worker)
    assert len(await repo.enqueue_research_jobs(S, [p.id])) == 1


async def test_process_job_claims_and_failure_recording_errors_are_contained(monkeypatch) -> None:
    repo, p = await _repo_with()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])

    def boom(*a, **k):
        raise RuntimeError("pipeline down")

    async def boom_update(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "run_research", boom)
    monkeypatch.setattr(repo, "update_prospect_research", boom_update)
    await worker.process_job(repo, job)  # must not raise
    stored = repo._jobs[job.id]
    assert stored.status == ResearchStatusEnum.FAILED
    assert stored.attempts == 1  # was claimed through the normal claim path

    # an already-claimed job is skipped, not run twice
    await worker.process_job(repo, job)
    assert repo._jobs[job.id].attempts == 1


async def test_real_northwind_prospect_gets_no_fixture_facts() -> None:
    repo, p = await _repo_with(name="Someone Else", company="Northwind Traders")
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    await worker.process_job(repo, job)
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL
    assert got.brief.facts == []


async def test_fixture_requires_name_and_company_or_explicit_key() -> None:
    _, exact = await _repo_with()
    assert worker._fixture_key_for(exact) == "northwind"
    _, name_only = await _repo_with(name="Dana Reyes", company="Other Co")
    assert worker._fixture_key_for(name_only) is None
    keyed = name_only.model_copy(update={"fixtureKey": "harborview"})
    assert worker._fixture_key_for(keyed) == "harborview"


async def test_no_fact_briefs_are_not_cached_and_notes_change_cache_key() -> None:
    repo, p = await _repo_with(name="Nobody", company="Real Co")
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    await worker.process_job(repo, job)
    assert repo._brief_cache == {}

    repo2, p2 = await _repo_with()
    (job,) = await repo2.enqueue_research_jobs(S, [p2.id])
    await worker.process_job(repo2, job)
    assert len(repo2._brief_cache) == 1
    key_before = worker._cache_key(p2)
    edited = await repo2.update_prospect(S, p2.id, ProspectUpdateInput(notes="new note"))
    assert worker._cache_key(edited) != key_before


async def test_seed_has_no_ready_prospect_without_brief_and_default_list_is_idempotent() -> None:
    repo = MemoryStorageRepository(seed=True)
    for p in await repo.get_prospects("seller-default"):
        assert p.researchStatus in (ResearchStatusEnum.NOT_STARTED, ResearchStatusEnum.FAILED) or p.brief
    a = await repo.ensure_default_list("new-seller")
    b = await repo.ensure_default_list("new-seller")
    assert a.id == b.id and len(await repo.get_lists("new-seller")) == 1
    assert await repo.list_completed_calls("new-seller") == []


async def test_dev_auth_refused_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        async with lifespan(app):
            pass
    monkeypatch.setattr(settings, "environment", "local")
    async with lifespan(app):
        pass
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "environment", "production")
    async with lifespan(app):
        pass


async def test_cache_key_is_seller_scoped() -> None:
    _, p = await _repo_with()
    other = p.model_copy(update={"sellerId": "seller-2"})
    assert worker._cache_key(p) != worker._cache_key(other)

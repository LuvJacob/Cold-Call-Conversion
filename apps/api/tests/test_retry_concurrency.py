"""Concurrency tests for research retries and backoff (gap coverage)."""

import asyncio

import pytest

from cold_call_api.config import settings
from cold_call_api.models import ProspectInput, ResearchStatusEnum
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"
H = {"X-Seller-ID": S}


async def _setup():
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(S, lst.id, [ProspectInput(name="Pat", company="Real Co", role="VP")])
    (job,) = await repo.enqueue_research_jobs(S, [created[0].id])
    return repo, created[0], job


def _flaky(monkeypatch, failures):
    calls = {"n": 0, "active": 0, "max_active": 0}
    real = worker.run_research

    def flaky(*a, **kw):
        calls["n"] += 1
        calls["active"] += 1
        calls["max_active"] = max(calls["max_active"], calls["active"])
        try:
            if calls["n"] <= failures:
                raise RuntimeError("boom")
            return real(*a, **kw)
        finally:
            calls["active"] -= 1

    monkeypatch.setattr(worker, "run_research", flaky)
    return calls


@pytest.mark.parametrize("lease", [90, 1])
async def test_reenqueue_during_backoff_creates_no_duplicate(monkeypatch, client, lease) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    monkeypatch.setattr(settings, "research_lease_seconds", lease)
    monkeypatch.setattr(settings, "research_retry_base_seconds", 30.0)
    repo, p, job = await _setup()
    calls = _flaky(monkeypatch, 1)
    in_backoff, release = asyncio.Event(), asyncio.Event()

    async def sleep(d):
        in_backoff.set()
        await release.wait()

    task = asyncio.create_task(worker.process_job(repo, job, sleep=sleep))
    await asyncio.wait_for(in_backoff.wait(), 5)
    assert repo._jobs[job.id].status == ResearchStatusEnum.QUEUED

    # direct enqueue and the HTTP endpoint must both skip the waiting job
    assert await repo.enqueue_research_jobs(S, [p.id]) == []
    from cold_call_api.storage import set_repository
    set_repository(repo)
    res = await client.post("/v1/research", headers=H, json={"prospectIds": [p.id]})
    assert res.status_code in (200, 202), res.text
    assert len(repo._jobs) == 1

    release.set()
    await asyncio.wait_for(task, 10)
    assert calls["n"] == 2 and calls["max_active"] == 1
    assert repo._jobs[job.id].status == ResearchStatusEnum.PARTIAL and len(repo._jobs) == 1


async def test_worker_loop_does_not_steal_job_in_backoff(monkeypatch) -> None:
    """run_worker_loop claims any QUEUED job; it must not start a second runner during backoff."""
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    monkeypatch.setattr(settings, "research_retry_base_seconds", 30.0)
    repo, p, job = await _setup()
    calls = _flaky(monkeypatch, 1)
    in_backoff, release = asyncio.Event(), asyncio.Event()

    async def sleep(d):
        in_backoff.set()
        await release.wait()

    task = asyncio.create_task(worker.process_job(repo, job, sleep=sleep))
    await asyncio.wait_for(in_backoff.wait(), 5)
    await worker.run_worker_loop(repo, once=True)  # would run attempt 2 immediately, skipping backoff
    assert calls["n"] == 1, "worker loop ran the job while it was waiting in backoff"
    release.set()
    await asyncio.wait_for(task, 10)
    assert calls["max_active"] == 1


async def test_domain_change_during_backoff_stops_retry(monkeypatch) -> None:
    from cold_call_api.models import ProspectUpdateInput

    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p, job = await _setup()
    calls = _flaky(monkeypatch, 99)
    in_backoff, release = asyncio.Event(), asyncio.Event()

    async def sleep(d):
        in_backoff.set()
        await release.wait()

    task = asyncio.create_task(worker.process_job(repo, job, sleep=sleep))
    await asyncio.wait_for(in_backoff.wait(), 5)
    await repo.update_prospect(S, p.id, ProspectUpdateInput(companyDomain="real.co"))
    release.set()
    await asyncio.wait_for(task, 10)
    assert calls["n"] == 1
    got = await repo.get_prospect(S, p.id)
    assert got.revision == 1
    assert repo._jobs[job.id].status == ResearchStatusEnum.FAILED


@pytest.mark.parametrize(
    "raw",
    ["[::1]", "http://[::1]:80/", "127.0.0.1", "2130706433", "0x7f000001", "127.1", "ftp://example.com",
     "a_b.com", "a" * 250 + ".com", "a" * 64 + ".com", "localhost", "example..com", ".example.com", "http://",
     "//example.com", "example.com\\@evil.com", "example.com\x00"],
)
def test_domain_garbage_rejected_more(raw) -> None:
    from cold_call_api.models import normalize_company_domain

    with pytest.raises(ValueError):
        normalize_company_domain(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [("m\u00fcnchen.de", "xn--mnchen-3ya.de"), ("\u0430pple.com", "xn--pple-43d.com"), ("HTTP://EXAMPLE.COM", "example.com"),
     ("example.com:8080", "example.com")],
)
def test_domain_idn_normalized_to_punycode(raw, expected) -> None:
    from cold_call_api.models import normalize_company_domain

    assert normalize_company_domain(raw) == expected


async def test_csv_bad_domain_not_echoed_and_good_rows_kept(client) -> None:
    lid = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    csv = "Name,Company,Role,Website\nA,Acme,CTO,acme.com\nB,Acme,CEO,http://user:pw@evil.com/SECRETPATH\n"
    res = await client.post(f"/v1/lists/{lid}/import", headers=H, files={"file": ("p.csv", csv.encode(), "text/csv")})
    data = res.json()
    assert len(data["imported"]) == 1 and len(data["rejectedRows"]) == 1
    assert "pw" not in res.text and "SECRETPATH" not in res.text

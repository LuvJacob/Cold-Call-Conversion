"""Fix-round tests: backoff claim guard, stale runner, deterministic errors, domain and 422 hardening."""

import pytest
from httpx import AsyncClient

from cold_call_api.config import settings
from cold_call_api.models import BriefModel, ProspectInput, ResearchStatusEnum, normalize_company_domain
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"
H = {"X-Seller-ID": S}


async def _repo_prospect():
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(S, lst.id, [ProspectInput(name="Pat", company="Real Co", role="VP")])
    return repo, created[0]


async def _no_sleep(d):
    raise AssertionError("must not back off")


@pytest.mark.parametrize(
    "raw",
    ["foo.localhost", "printer.local", "db.internal", "host.localdomain", "x.home.arpa", "1.0.0.127.in-addr.arpa",
     "a.test", "a.invalid", "example.com..", "exam​ple.com", "example.com⁠", "﻿example.com"],
)
def test_domain_reserved_and_invisible_rejected(raw) -> None:
    with pytest.raises(ValueError):
        normalize_company_domain(raw)


def test_domain_still_accepts_normal_and_example() -> None:
    assert normalize_company_domain("https://www.example.com:8080/x") == "example.com"
    assert normalize_company_domain("example.com.") == "example.com"


async def test_422_does_not_echo_input(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    res = await client.post(
        f"/v1/lists/{lid}/prospects", headers=H,
        json={"name": "C", "company": "Acme", "role": "CTO", "companyDomain": "u:pw@x.com"},
    )
    assert res.status_code == 422
    first = res.json()["detail"][0]
    assert "u:pw" not in res.text and "input" not in first and "ctx" not in first
    assert any("companyDomain" in e["loc"] for e in res.json()["detail"])
    assert first["type"] and first["msg"]


@pytest.mark.parametrize("exc", [KeyError, TypeError, AttributeError])
async def test_deterministic_errors_not_retried(monkeypatch, exc) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        raise exc("x")

    monkeypatch.setattr(worker, "run_research", boom)
    await worker.process_job(repo, job, sleep=_no_sleep)
    assert calls["n"] == 1
    assert (await repo.get_prospect(S, p.id)).researchStatus == ResearchStatusEnum.FAILED


async def test_validation_error_not_retried(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        BriefModel.model_validate({})

    monkeypatch.setattr(worker, "run_research", boom)
    await worker.process_job(repo, job, sleep=_no_sleep)
    assert calls["n"] == 1


async def test_runtime_and_timeout_errors_are_retried(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        raise (RuntimeError("x") if calls["n"] == 1 else TimeoutError("t"))

    monkeypatch.setattr(worker, "run_research", boom)

    async def fake_sleep(d):
        pass

    await worker.process_job(repo, job, sleep=fake_sleep)
    assert calls["n"] == 3


async def test_stale_runner_does_not_overwrite_new_job(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])

    def boom(*a, **kw):
        raise RuntimeError("x")

    async def lost(*a, **kw):
        return False

    monkeypatch.setattr(worker, "run_research", boom)
    monkeypatch.setattr(repo, "requeue_research_job", lost)
    await worker.process_job(repo, job, sleep=_no_sleep)
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.RUNNING and got.researchError is None


async def test_requeue_sets_not_before_and_poller_skips_until_due() -> None:
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    claimed = await repo.claim_research_job("w", job_id=job.id)
    assert await repo.requeue_research_job(claimed.id, "e", 100, delay_seconds=60)
    assert repo._jobs[job.id].notBefore
    assert await repo.claim_research_job("poller") is None
    assert await repo.enqueue_research_jobs(S, [p.id]) == []  # idempotent during backoff
    again = await repo.claim_research_job("own", job_id=job.id)  # the owner may re-claim
    assert again and again.attempts == 2 and again.notBefore is None

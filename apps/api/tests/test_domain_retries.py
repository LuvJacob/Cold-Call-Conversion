"""Tests for companyDomain and research retries (Lane C)."""

import pytest
from httpx import AsyncClient

from cold_call_api.config import settings
from cold_call_api.models import ProspectInput, ProspectUpdateInput, ResearchStatusEnum, normalize_company_domain
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"
H = {"X-Seller-ID": S}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("example.com", "example.com"),
        ("  HTTPS://WWW.Example.COM:8443/path?q=1#x ", "example.com"),
        ("http://sub.example.co.uk/", "sub.example.co.uk"),
        ("www.example.com/about", "example.com"),
        ("example.com.", "example.com"),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_domain(raw, expected) -> None:
    assert normalize_company_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["192.168.1.1", "http://10.0.0.1/x", "[::1]", "user:pw@example.com", "ftp://example.com",
     "javascript:alert(1)", "localhost", "-bad.example.com", "exa mple.com", "example..com",
     "http://example.com:99999", "example.123", "a" * 64 + ".com"],
)
def test_normalize_domain_rejects(raw) -> None:
    with pytest.raises(ValueError):
        normalize_company_domain(raw)


async def test_create_patch_and_revision_bump(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    res = await client.post(
        f"/v1/lists/{lid}/prospects", headers=H,
        json={"name": "A", "company": "Acme", "role": "CTO", "companyDomain": "https://www.Acme.com/x"},
    )
    p = res.json()[0]
    assert p["companyDomain"] == "acme.com"
    assert p["revision"] == 0

    res = await client.patch(f"/v1/prospects/{p['id']}", headers=H, json={"companyDomain": "acme.io"})
    assert res.json()["companyDomain"] == "acme.io" and res.json()["revision"] == 1

    res = await client.patch(f"/v1/prospects/{p['id']}", headers=H, json={"name": "B"})
    assert res.json()["companyDomain"] == "acme.io"  # omitted = unchanged

    res = await client.patch(f"/v1/prospects/{p['id']}", headers=H, json={"companyDomain": ""})
    assert res.json()["companyDomain"] is None and res.json()["revision"] == 3

    res = await client.patch(f"/v1/prospects/{p['id']}", headers=H, json={"companyDomain": "1.2.3.4"})
    assert res.status_code == 422
    res = await client.post(
        f"/v1/lists/{lid}/prospects", headers=H,
        json={"name": "C", "company": "Acme", "role": "CTO", "companyDomain": "u@acme.com"},
    )
    assert res.status_code == 422


async def test_prospect_without_domain_has_null(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    res = await client.post(f"/v1/lists/{lid}/prospects", headers=H, json={"name": "A", "company": "Acme", "role": "CTO"})
    assert res.json()[0]["companyDomain"] is None


@pytest.mark.parametrize("header", ["Website", "domain", "Company Website", "url", "Company_Domain"])
async def test_csv_domain_aliases(client: AsyncClient, header) -> None:
    lid = (await client.post("/v1/lists", headers=H, json={"name": "L"})).json()["id"]
    csv = f"Name,Company,Role,{header}\nJane,Acme,CTO,https://www.acme.com/\nBad,Acme,CEO,10.0.0.1\n"
    res = await client.post(f"/v1/lists/{lid}/import", headers=H, files={"file": ("p.csv", csv.encode(), "text/csv")})
    data = res.json()
    assert data["imported"][0]["companyDomain"] == "acme.com"
    assert len(data["rejectedRows"]) == 1 and "website" in data["rejectedRows"][0]["message"]
    assert "10.0.0.1" not in data["rejectedRows"][0]["message"]


async def _repo_prospect(domain=None):
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(
        S, lst.id, [ProspectInput(name="Pat", company="Real Co", role="VP", companyDomain=domain)]
    )
    return repo, created[0]


async def test_cache_key_includes_domain() -> None:
    repo, p = await _repo_prospect("a.com")
    edited = await repo.update_prospect(S, p.id, ProspectUpdateInput(companyDomain="b.com"))
    assert worker._cache_key(edited) != worker._cache_key(p)


async def test_agent_prospect_receives_company_domain(monkeypatch) -> None:
    repo, p = await _repo_prospect("acme.com")
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    seen = {}
    real = worker.run_research

    def spy(agent_prospect, **kw):
        seen["domain"] = agent_prospect.company_domain
        return real(agent_prospect, **kw)

    monkeypatch.setattr(worker, "run_research", spy)
    await worker.process_job(repo, job)
    assert seen["domain"] == "acme.com"


# --- retries ---

def _flaky(monkeypatch, failures):
    calls = {"n": 0}
    real = worker.run_research

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise RuntimeError("secret-internal-detail")
        return real(*a, **kw)

    monkeypatch.setattr(worker, "run_research", flaky)
    return calls


async def test_retry_succeeds_on_second_attempt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = _flaky(monkeypatch, 1)
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    await worker.process_job(repo, job, sleep=fake_sleep)
    assert calls["n"] == 2 and len(sleeps) == 1
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL and got.researchError is None
    stored = repo._jobs[job.id]
    assert stored.attempts == 2 and stored.status == ResearchStatusEnum.PARTIAL


async def test_gives_up_after_max_attempts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = _flaky(monkeypatch, 99)
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    await worker.process_job(repo, job, sleep=fake_sleep)
    assert calls["n"] == 3 and len(sleeps) == 2
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.FAILED
    assert "secret-internal-detail" not in (got.researchError or "")
    assert repo._jobs[job.id].status == ResearchStatusEnum.FAILED and repo._jobs[job.id].attempts == 3
    # a job that is already done is not run again
    await worker.process_job(repo, job, sleep=fake_sleep)
    assert calls["n"] == 3


async def test_no_retry_when_revision_changed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        raise RuntimeError("x")

    monkeypatch.setattr(worker, "run_research", boom)
    real_get = repo.get_prospect
    state = {"edited": False}

    async def get_and_edit(seller, pid):
        got = await real_get(seller, pid)
        if calls["n"] == 1 and not state["edited"]:
            state["edited"] = True  # user edits the prospect right after the failed attempt
            await repo.update_prospect(S, pid, ProspectUpdateInput(notes="edited"))
            return await real_get(seller, pid)
        return got

    monkeypatch.setattr(repo, "get_prospect", get_and_edit)

    async def fake_sleep(d):
        raise AssertionError("must not back off for a stale job")

    await worker.process_job(repo, job, sleep=fake_sleep)
    assert calls["n"] == 1
    got = await real_get(S, p.id)
    assert got.revision == 1 and got.researchStatus == ResearchStatusEnum.NOT_STARTED  # edit not overwritten


async def test_backoff_schedule_and_injected_sleep(monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 4)
    monkeypatch.setattr(settings, "research_retry_base_seconds", 5.0)
    monkeypatch.setattr(worker.random, "random", lambda: 0.5)  # jitter factor exactly 1.0
    assert [worker.backoff_seconds(n, 5.0, lambda: 0.5) for n in (1, 2, 3)] == [5.0, 10.0, 20.0]
    assert worker.backoff_seconds(1, 5.0, lambda: 0.0) == 3.75
    assert worker.backoff_seconds(1, 5.0, lambda: 1.0) == 6.25
    assert worker.backoff_seconds(20, 5.0, lambda: 0.5) == 300.0
    repo, p = await _repo_prospect()
    (job,) = await repo.enqueue_research_jobs(S, [p.id])
    _flaky(monkeypatch, 99)
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    await worker.process_job(repo, job, sleep=fake_sleep)
    assert sleeps == [5.0, 10.0, 20.0]

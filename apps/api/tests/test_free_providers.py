"""Worker wiring for RESEARCH_PROVIDERS=free. No network: the free-source builder is replaced."""

import pytest

from cold_call_agents.providers import MockLLM, MockProfiles, MockSearch
from cold_call_api.models import ProspectInput, ResearchStatusEnum
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"


async def _job(name, company):
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(
        S, lst.id, [ProspectInput(name=name, company=company, role="VP", phone="1")]
    )
    (job,) = await repo.enqueue_research_jobs(S, [created[0].id])
    return repo, created[0], job


@pytest.fixture
def spy(monkeypatch):
    calls = []

    def fake_build(agent_prospect, budget):
        calls.append(agent_prospect.company)
        return MockLLM(), MockSearch([]), MockProfiles(None, None)

    monkeypatch.setattr(worker, "build_free_providers", fake_build)
    return calls


async def test_default_never_uses_free_sources(spy, monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_PROVIDERS", raising=False)
    repo, p, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)
    assert spy == []
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL
    assert "No live research providers are connected" in got.brief.uncertainty[0]


@pytest.mark.parametrize("value", ["", "none", "tavily"])
async def test_other_values_do_not_enable_free_sources(spy, monkeypatch, value) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", value)
    repo, _, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)
    assert spy == []


async def test_free_sources_used_when_enabled_and_no_fixture_match(spy, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "Free")
    repo, p, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)
    assert spy == ["Real Company"]
    got = await repo.get_prospect(S, p.id)
    assert "Free public sources found no matching facts" in got.brief.uncertainty[0]


async def test_fixture_match_wins_over_free_sources(spy, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "free")
    repo, p, job = await _job("Dana Reyes", "Northwind Logistics Sample Inc")
    await worker.process_job(repo, job)
    assert spy == []
    got = await repo.get_prospect(S, p.id)
    assert got.brief.facts


# ---- extra worker checks (tester) -------------------------------------------------


async def test_free_provider_builder_crash_fails_the_job_cleanly(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "free")

    def boom(agent_prospect, budget):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(worker, "build_free_providers", boom)
    repo, p, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)  # must not raise
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.FAILED
    assert "secret internal detail" not in (got.researchError or "")


async def test_free_mode_with_dead_network_gives_partial_empty_brief_not_made_up_facts(monkeypatch) -> None:
    """Real build_free_providers + real research code, but every HTTP call is refused by a mock transport."""
    import httpx

    from cold_call_agents.free_sources import build_free_providers as real_build
    from cold_call_agents.free_sources.http import HttpClient

    seen = []

    def refuse(req):
        seen.append(req.url.host)
        raise httpx.ConnectError("no network", request=req)

    monkeypatch.setenv("RESEARCH_PROVIDERS", "free")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(
        worker, "build_free_providers",
        lambda ap, b: real_build(ap, b, {}, http=HttpClient(transport=httpx.MockTransport(refuse), sleep=lambda s: None)),
    )
    repo, p, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL
    assert not got.brief.facts
    assert "Free public sources found no matching facts" in got.brief.uncertainty[0]
    assert seen and set(seen) <= {"www.wikidata.org"}  # no EDGAR without SEC_USER_AGENT, no homepage without a domain


async def test_unset_env_makes_no_http_client_at_all(monkeypatch) -> None:
    import httpx

    monkeypatch.delenv("RESEARCH_PROVIDERS", raising=False)

    def forbidden(*a, **k):
        raise AssertionError("network client constructed in default mode")

    monkeypatch.setattr(httpx.Client, "__init__", forbidden)
    repo, p, job = await _job("Someone Real", "Real Company")
    await worker.process_job(repo, job)
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL

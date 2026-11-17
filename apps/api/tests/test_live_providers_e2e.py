"""Live mode through the real build_live_providers with a failing transport (nothing leaves the process),
plus cross-mode cache isolation and health secrecy."""

import functools
import json
import logging

import httpx
import pytest

from cold_call_agents.live import build_live_providers
from cold_call_agents.providers import MockLLM, MockProfiles, MockSearch, load_fixture, mocks_from_fixture
from cold_call_api.models import ProspectInput, ResearchStatusEnum
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"
SECRETS = {
    "TAVILY_API_KEY": "fake-tvly-SECRET123",
    "WATSONX_API_KEY": "fake-ibm-SECRET456",
    "PDL_API_KEY": "fake-pdl-SECRET789",
    "GEMINI_API_KEY": "fake-gem-SECRET000",
    "WATSONX_URL": "https://127.0.0.1:9",
    "WATSONX_PROJECT_ID": "proj-SECRETID",
}
EMPTY = lambda: (MockLLM(), MockSearch([]), MockProfiles(None, None))  # noqa: E731


async def _job(name="Someone Real", company="Real Company"):
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(S, lst.id, [ProspectInput(name=name, company=company, role="VP", phone="1")])
    (job,) = await repo.enqueue_research_jobs(S, [created[0].id])
    return repo, created[0], job


@pytest.fixture
def offline_live(monkeypatch):
    """Real live factory, every request fails with a network error; records hosts contacted."""
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        raise httpx.ConnectError("blocked")

    real = build_live_providers
    monkeypatch.setattr(
        worker, "build_live_providers",
        lambda ap, b, env: real(ap, b, env, transport=httpx.MockTransport(handler), free_providers=EMPTY(),
                                sleep=lambda s: None),
    )
    monkeypatch.setenv("RESEARCH_PROVIDERS", "live")
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    return hosts


async def test_live_network_failure_is_partial_with_notes_and_no_secrets(offline_live, caplog) -> None:
    repo, p, job = await _job()
    with caplog.at_level(logging.DEBUG):
        await worker.process_job(repo, job)
    got = await repo.get_prospect(S, p.id)
    assert got.researchStatus == ResearchStatusEnum.PARTIAL
    assert got.brief.facts == [] and got.brief.sources == []
    assert any("failed" in u for u in got.brief.uncertainty)  # provider failures are flagged, not guessed
    assert offline_live and set(offline_live) <= {"api.tavily.com", "api.peopledatalabs.com", "iam.cloud.ibm.com"}
    blob = got.model_dump_json() + str(got.researchError) + caplog.text + "".join(r.getMessage() for r in caplog.records)
    for v in SECRETS.values():
        assert v not in blob
    assert "SECRET" not in blob


async def test_live_failure_not_cached(offline_live) -> None:
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    prospect = await repo.get_prospect(S, p.id)
    for mode in ("", "free", "live"):
        assert await repo.get_cached_briefing(worker._cache_key(prospect, mode), max_age_days=7) is None


async def test_cached_brief_not_served_across_modes(monkeypatch) -> None:
    """Same prospect: a brief cached in free mode must not be served in live (or unset) mode, and vice versa."""
    person = load_fixture("northwind")["prospect"]
    monkeypatch.setattr(worker, "_fixture_key_for", lambda p: None)  # researched path, not the fixture shortcut
    full = lambda *a, **k: mocks_from_fixture(load_fixture("northwind"))  # noqa: E731
    monkeypatch.setattr(worker, "build_free_providers", full)
    monkeypatch.setattr(worker, "build_live_providers", lambda ap, b, env: EMPTY())

    repo, p, job = await _job(person["name"], person["company"])
    monkeypatch.setenv("RESEARCH_PROVIDERS", "free")
    await worker.process_job(repo, job)
    first = await repo.get_prospect(S, p.id)
    assert first.researchStatus == ResearchStatusEnum.READY and first.brief.facts

    async def rerun(mode):
        monkeypatch.setenv("RESEARCH_PROVIDERS", mode)
        (j,) = await repo.enqueue_research_jobs(S, [p.id])
        await worker.process_job(repo, j)
        return await repo.get_prospect(S, p.id)

    live = await rerun("live")
    assert live.researchStatus == ResearchStatusEnum.PARTIAL and not live.brief.facts
    unset = await rerun("")
    assert not unset.brief.facts
    # free mode again: its own cached brief is still served
    assert (await rerun("free")).brief.facts


async def test_health_never_leaks_any_secret(client, monkeypatch) -> None:
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_PROVIDER", "bogus-SECRETPROVIDER")
    monkeypatch.setenv("RESEARCH_PROVIDERS", "live")
    res = await client.get("/healthz/research")
    assert res.json() == {"mode": "live", "tavily": True, "pdl": True, "llm": "watsonx", "watsonx": True, "gemini": True}
    assert "SECRET" not in res.text


async def test_health_whitespace_only_key_counts_as_unset(client, monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "   ")
    assert (await client.get("/healthz/research")).json()["tavily"] is False

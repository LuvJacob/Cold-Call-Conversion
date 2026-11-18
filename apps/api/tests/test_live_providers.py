"""Worker wiring for RESEARCH_PROVIDERS=live. Offline: build_live_providers is replaced by fakes."""

import logging

import pytest

from cold_call_agents.providers import MockLLM, MockProfiles, MockSearch, load_fixture, mocks_from_fixture
from cold_call_api import config
from cold_call_api.config import settings
from cold_call_api.models import ProspectInput, ResearchStatusEnum
from cold_call_api.services import worker
from cold_call_api.storage.memory import MemoryStorageRepository

S = "seller-1"
FAKE_KEY = "sk-fake-secret-123456"


class Closable:
    def __init__(self, inner):
        self.inner = inner
        self.closed = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def close(self):
        self.closed += 1


async def _job(name="Someone Real", company="Real Company"):
    repo = MemoryStorageRepository(seed=False)
    lst = await repo.create_list(S, "L")
    created, _ = await repo.create_prospects(
        S, lst.id, [ProspectInput(name=name, company=company, role="VP", phone="1")]
    )
    (job,) = await repo.enqueue_research_jobs(S, [created[0].id])
    return repo, created[0], job


@pytest.fixture
def factory(monkeypatch):
    """Fake build_live_providers (empty providers); records calls and what it handed out."""
    state = {"calls": [], "built": [], "trio": lambda: (MockLLM(), MockSearch([]), MockProfiles(None, None))}

    def fake(agent_prospect, budget, env):
        state["calls"].append((agent_prospect.company, env))
        trio = tuple(Closable(p) for p in state["trio"]())
        state["built"].append(trio)
        return trio

    monkeypatch.setattr(worker, "build_live_providers", fake)
    monkeypatch.setenv("RESEARCH_PROVIDERS", "live")
    return state


def _all_closed(state):
    return all(p.closed == 1 for trio in state["built"] for p in trio)


async def test_live_mode_uses_factory_with_process_env(factory, monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", FAKE_KEY)
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    assert [c[0] for c in factory["calls"]] == ["Real Company"]
    assert factory["calls"][0][1]["TAVILY_API_KEY"] == FAKE_KEY
    got = await repo.get_prospect(S, p.id)
    assert "Live research providers found no matching facts" in got.brief.uncertainty[0]
    assert _all_closed(factory)


async def test_fixture_wins_over_live(factory) -> None:
    repo, p, job = await _job("Dana Reyes", "Northwind Logistics Sample Inc")
    await worker.process_job(repo, job)
    assert factory["calls"] == []
    assert (await repo.get_prospect(S, p.id)).brief.facts


async def test_close_called_on_exception(factory, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(worker, "run_research", boom)
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    assert (await repo.get_prospect(S, p.id)).researchStatus == ResearchStatusEnum.FAILED
    assert len(factory["built"]) == 1 and _all_closed(factory)


async def test_close_called_on_every_retry_attempt(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "research_max_attempts", 3)
    real = worker.run_research
    attempts = []

    def flaky(*a, **k):
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("transient")
        return real(*a, **k)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(worker, "run_research", flaky)
    repo, p, job = await _job()
    await worker.process_job(repo, job, sleep=no_sleep)
    assert len(factory["built"]) == 3 and _all_closed(factory)
    assert (await repo.get_prospect(S, p.id)).researchStatus == ResearchStatusEnum.PARTIAL


async def test_failing_close_does_not_skip_others_or_break_job(factory) -> None:
    class BadClose(Closable):
        def close(self):
            raise RuntimeError("close failed")

    def trio():
        return BadClose(MockLLM()), MockSearch([]), MockProfiles(None, None)

    factory["trio"] = trio
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    assert (await repo.get_prospect(S, p.id)).researchStatus == ResearchStatusEnum.PARTIAL


async def test_partial_brief_not_cached_in_live_mode(factory) -> None:
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    prospect = await repo.get_prospect(S, p.id)
    assert await repo.get_cached_briefing(worker._cache_key(prospect, "live"), max_age_days=7) is None


async def test_ready_brief_cached_under_live_key_only(factory, monkeypatch) -> None:
    factory["trio"] = lambda: mocks_from_fixture(load_fixture("northwind"))
    person = load_fixture("northwind")["prospect"]
    monkeypatch.setattr(worker, "_fixture_key_for", lambda p: None)  # force the live path for the sample person
    repo, p, job = await _job(person["name"], person["company"])
    await worker.process_job(repo, job)
    prospect = await repo.get_prospect(S, p.id)
    assert prospect.researchStatus == ResearchStatusEnum.READY
    assert await repo.get_cached_briefing(worker._cache_key(prospect, "live"), max_age_days=7)
    assert await repo.get_cached_briefing(worker._cache_key(prospect, "free"), max_age_days=7) is None
    assert await repo.get_cached_briefing(worker._cache_key(prospect), max_age_days=7) is None


async def test_cache_key_differs_across_modes() -> None:
    repo, p, _ = await _job()
    prospect = await repo.get_prospect(S, p.id)
    keys = {worker._cache_key(prospect, m) for m in ("", "free", "live")}
    assert len(keys) == 3
    assert worker._cache_key(prospect) == worker._cache_key(prospect, "")


@pytest.mark.parametrize("mode", ["", "free"])
async def test_unset_and_free_do_not_call_live_factory(factory, monkeypatch, mode) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", mode)
    monkeypatch.setattr(
        worker, "build_free_providers", lambda ap, b: (MockLLM(), MockSearch([]), MockProfiles(None, None))
    )
    repo, _, job = await _job()
    await worker.process_job(repo, job)
    assert factory["calls"] == []


async def test_unknown_value_behaves_as_unset(factory, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "bogus")
    repo, p, job = await _job()
    await worker.process_job(repo, job)
    assert factory["calls"] == []
    assert "No live research providers are connected" in (await repo.get_prospect(S, p.id)).brief.uncertainty[0]


def test_unknown_value_warns_once(monkeypatch, caplog) -> None:
    config._warned_modes.discard("bogus")
    monkeypatch.setenv("RESEARCH_PROVIDERS", "bogus")
    with caplog.at_level(logging.WARNING, logger="cold_call_api.config"):
        assert config.research_mode() == ""
        assert config.research_mode() == ""
    assert len([r for r in caplog.records if "Unknown RESEARCH_PROVIDERS" in r.getMessage()]) == 1


def test_mode_is_case_insensitive(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", " LIVE ")
    assert config.research_mode() == "live"


async def test_research_health_reports_booleans_only(client, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "live")
    monkeypatch.setenv("TAVILY_API_KEY", FAKE_KEY)
    monkeypatch.setenv("WATSONX_API_KEY", FAKE_KEY + "w")
    monkeypatch.setenv("WATSONX_URL", "https://fake.example")
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    res = await client.get("/healthz/research")
    assert res.status_code == 200
    assert res.json() == {
        "mode": "live", "tavily": True, "pdl": False, "llm": "watsonx", "watsonx": False, "gemini": False,
    }
    assert "sk-fake" not in res.text and "fake.example" not in res.text


async def test_research_health_default_mode(client, monkeypatch) -> None:
    for name in ("RESEARCH_PROVIDERS", "TAVILY_API_KEY", "PDL_API_KEY", "GEMINI_API_KEY", "WATSONX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    data = (await client.get("/healthz/research")).json()
    assert data["mode"] == "default" and data["tavily"] is False and data["pdl"] is False


async def test_research_health_requires_auth_in_jwt_mode(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_secret", "unit-test-secret-with-at-least-32-bytes!!")
    assert (await client.get("/healthz/research")).status_code == 401
    assert (await client.get("/healthz/research", headers={"X-Seller-ID": "x"})).status_code == 401


async def test_research_health_watsonx_needs_https_url(client, monkeypatch) -> None:
    monkeypatch.setenv("WATSONX_API_KEY", "k")
    monkeypatch.setenv("WATSONX_PROJECT_ID", "p")
    monkeypatch.setenv("WATSONX_URL", "http://insecure.example")
    assert (await client.get("/healthz/research")).json()["watsonx"] is False
    monkeypatch.setenv("WATSONX_URL", "https://ok.example")
    assert (await client.get("/healthz/research")).json()["watsonx"] is True


async def test_factory_raising_fails_job_cleanly(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDERS", "live")

    def boom(agent_prospect, budget, env):
        raise RuntimeError("factory down")

    monkeypatch.setattr(worker, "build_live_providers", boom)
    repo, p, job = await _job()
    await worker.process_job(repo, job)  # must not raise (nothing to close, None tolerated)
    assert (await repo.get_prospect(S, p.id)).researchStatus == ResearchStatusEnum.FAILED


async def test_cache_hit_returns_original_status(factory, monkeypatch) -> None:
    """A READY brief that carries fallback notes in uncertainty stays READY when served from cache."""
    factory["trio"] = lambda: mocks_from_fixture(load_fixture("northwind"))
    person = load_fixture("northwind")["prospect"]
    monkeypatch.setattr(worker, "_fixture_key_for", lambda p: None)
    repo, p, job = await _job(person["name"], person["company"])
    await worker.process_job(repo, job)
    first = await repo.get_prospect(S, p.id)
    assert first.researchStatus == ResearchStatusEnum.READY
    (job2,) = await repo.enqueue_research_jobs(S, [p.id])
    brief = first.brief.model_copy(update={"uncertainty": ["fallback note"]})
    await repo.save_cached_briefing(worker._cache_key(first, "live"), brief, ResearchStatusEnum.READY)
    await worker.process_job(repo, job2)
    again = await repo.get_prospect(S, p.id)
    assert again.researchStatus == ResearchStatusEnum.READY
    assert again.brief.uncertainty == ["fallback note"]

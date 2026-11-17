import httpx

from cold_call_agents.free_sources import TemplateLLM
from cold_call_agents.live import build_live_providers
from cold_call_agents.live.gemini import GeminiLLM
from cold_call_agents.live.pdl import PdlProfiles
from cold_call_agents.live.tavily import TavilySearch
from cold_call_agents.live.watsonx import WatsonxLLM
from cold_call_agents.models import Prospect
from cold_call_agents.researchers import Budget
from free_helpers import FakeNet, make_http
from live_helpers import Recorder, jresp, no_sleep
from cold_call_agents.free_sources.provider import FreeSources

PROSPECT = Prospect(prospect_id="p1", name="Jordan Sample", company="Acme Robotics Sample Inc", role="VP Ops",
                    company_domain="acme-robotics.example")
FULL = {
    "TAVILY_API_KEY": "t", "PDL_API_KEY": "p", "WATSONX_API_KEY": "w", "WATSONX_URL": "https://us-south.ml.cloud.ibm.com",
    "WATSONX_PROJECT_ID": "proj", "GEMINI_API_KEY": "g",
}


def free_stub(net=None):
    net = net or FakeNet()
    return (TemplateLLM(), FreeSources(PROSPECT.company, PROSPECT.company_domain, make_http(net), resolver=lambda h: ["93.184.216.34"]), None), net


def build(env, **kw):
    kw.setdefault("transport", httpx.MockTransport(lambda r: httpx.Response(500)))
    kw.setdefault("sleep", no_sleep)
    return build_live_providers(PROSPECT, Budget(), env, **kw)


def test_all_keys_gives_live_clients_and_default_watsonx():
    llm, search, profiles = build(FULL)
    assert isinstance(llm, WatsonxLLM) and isinstance(search, TavilySearch) and isinstance(profiles, PdlProfiles)
    assert llm.model_id == "ibm/granite-3-3-8b-instruct"
    assert search.max_searches == Budget().max_searches
    for c in (llm, search, profiles):
        c.close()


def test_llm_provider_gemini_and_model_override():
    llm, *_ = build({**FULL, "LLM_PROVIDER": "Gemini", "GEMINI_MODEL": "gemini-x"})
    assert isinstance(llm, GeminiLLM) and llm.model == "gemini-x"
    llm, *_ = build({**FULL, "WATSONX_MODEL_ID": "ibm/other"})
    assert llm.model_id == "ibm/other"


def test_pdl_threshold_env():
    *_, profiles = build({**FULL, "PDL_MIN_LIKELIHOOD": "8"})
    assert profiles.min_likelihood == 8
    *_, profiles = build({**FULL, "PDL_MIN_LIKELIHOOD": "banana"})
    assert profiles.min_likelihood == 6


def test_no_keys_falls_back_to_free_with_notes():
    free, net = free_stub()
    llm, search, profiles = build({}, free_providers=free)
    assert isinstance(llm, TemplateLLM)
    assert search.notes("company")[0].startswith("TAVILY_API_KEY not set")
    assert any("WATSONX_API_KEY" in n for n in search.notes("company"))
    assert profiles.notes("person")[0].startswith("PDL_API_KEY not set")
    # still works: company profile comes from the free sources
    assert profiles.company(PROSPECT.company, PROSPECT.company_domain) is not None
    assert not net.hosts() - {"www.wikidata.org", "en.wikipedia.org", "acme-robotics.example", SITE_HOST}
    search.close()


SITE_HOST = "www.acme-robotics.example"


def test_partial_keys_mix_live_and_free():
    free, _ = free_stub()
    llm, search, profiles = build({"TAVILY_API_KEY": "t", "LLM_PROVIDER": "gemini"}, free_providers=free)
    assert isinstance(search, TavilySearch) and isinstance(llm, TemplateLLM)
    assert any("GEMINI_API_KEY" in n for n in search.notes("company"))
    assert profiles.notes("company")[0].startswith("PDL_API_KEY not set")
    search.close()


def test_partial_watsonx_settings_fall_back():
    free, _ = free_stub()
    env = {**FULL, "WATSONX_PROJECT_ID": ""}
    llm, search, _ = build(env, free_providers=free)
    assert isinstance(llm, TemplateLLM) and isinstance(search, TavilySearch)
    assert any("WATSONX_PROJECT_ID" in n for n in search.notes("person"))
    llm, *_ = build({**FULL, "WATSONX_URL": "http://insecure.example"}, free_providers=free)
    assert isinstance(llm, TemplateLLM)


def test_unknown_llm_provider_notes_and_uses_watsonx():
    llm, search, _ = build({**FULL, "LLM_PROVIDER": "banana"})
    assert isinstance(llm, WatsonxLLM)
    assert any("Unknown LLM_PROVIDER" in n for n in search.notes("company"))


def test_keys_never_appear_in_notes_or_repr():
    free, _ = free_stub()
    _, search, profiles = build({"TAVILY_API_KEY": "SECRETVALUE"}, free_providers=free)
    assert "SECRETVALUE" not in " ".join(search.notes("company") + profiles.notes("company"))


def test_live_search_runs_through_factory_transport():
    rec = Recorder(jresp("tavily_search.json"))
    _, search, _ = build({"TAVILY_API_KEY": "t"}, transport=rec.transport, free_providers=free_stub()[0])
    assert len(search.search("Acme Robotics Sample Inc about", 3)) == 2
    assert rec.requests[0].headers["authorization"] == "Bearer t"


def test_failed_later_build_closes_clients_already_built(monkeypatch):
    import pytest
    from cold_call_agents.live import factory

    closed = []
    real_tavily = factory.build_tavily

    def tavily_spy(*a, **k):
        client = real_tavily(*a, **k)
        orig = client.close
        client.close = lambda: (closed.append("tavily"), orig())[1]
        return client

    def boom(*a, **k):
        raise RuntimeError("pdl build failed")

    monkeypatch.setattr(factory, "build_tavily", tavily_spy)
    monkeypatch.setattr(factory, "build_pdl", boom)
    with pytest.raises(RuntimeError, match="pdl build failed"):
        build(FULL)
    assert closed == ["tavily"]

"""http_requests in RunMetrics includes the live clients (retries and the watsonx IAM fetch)."""

import httpx

from conftest import TODAY, setup
from cold_call_agents.live.factory import build_live_providers
from cold_call_agents.live.gemini import build_gemini
from cold_call_agents.live.pdl import build_pdl
from cold_call_agents.live.tavily import build_tavily
from cold_call_agents.live.watsonx import build_watsonx
from cold_call_agents.metrics import http_request_count
from cold_call_agents.orchestrator import run_research_with_metrics
from live_helpers import Recorder, jresp, no_sleep

BASE = "https://us-south.ml.cloud.ibm.com"


def answer(request):
    host = request.url.host
    if host == "iam.cloud.ibm.com":
        return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    if "tavily" in host:
        return jresp("tavily_search.json")
    if "peopledatalabs" in host:
        return jresp("pdl_person.json" if "person" in request.url.path else "pdl_company.json")
    if "generativelanguage" in host:
        return jresp("gemini_generate.json")
    return jresp("watsonx_chat.json")


def test_each_live_client_counts_its_requests():
    tr = Recorder(answer).transport
    kw = dict(transport=tr, sleep=no_sleep)
    tav = build_tavily("k", 6, 60, **kw)
    tav.search("Acme news", 3)
    pdl = build_pdl("k", 60, **kw)
    pdl.person("Jordan Sample", "Acme Robotics Sample Inc")
    gem = build_gemini("k", 60, **kw)
    gem.complete("s", "p")
    wx = build_watsonx("k", BASE, "proj", 60, **kw)
    wx.complete("s", "p")
    assert http_request_count(tav) == 1
    assert http_request_count(pdl) == 1
    assert http_request_count(gem) == 1
    assert http_request_count(wx) == 2  # IAM token fetch + chat


def test_retries_count():
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else jresp("tavily_search.json")

    tav = build_tavily("k", 6, 60, transport=Recorder(flaky).transport, sleep=no_sleep)
    tav.search("Acme news", 3)
    assert len(calls) == 2 and http_request_count(tav) == 2


def test_live_run_metrics_include_live_clients():
    prospect, _, _, _ = setup("northwind")
    env = {"TAVILY_API_KEY": "t", "PDL_API_KEY": "p", "WATSONX_API_KEY": "w",
           "WATSONX_URL": BASE, "WATSONX_PROJECT_ID": "proj"}
    rec = Recorder(answer)
    llm, search, profiles = build_live_providers(prospect, env=env, transport=rec.transport, sleep=no_sleep, today=TODAY)
    try:
        _, m = run_research_with_metrics(prospect, llm=llm, search=search, profiles=profiles, today=TODAY, mode="live")
    finally:
        for c in (llm, search, profiles):
            c.close()
    assert len(rec.requests) > 0
    assert m.http_requests == len(rec.requests)  # search + profiles + LLM (incl. IAM), nothing missed


def test_free_mode_counting_still_works():
    class Http:
        requests_made = 0

    class S:
        http = Http()

        def search(self, q, n):
            Http.requests_made += 2
            return []

    prospect, llm, _, profiles = setup("northwind")
    _, m = run_research_with_metrics(prospect, llm=llm, search=S(), profiles=profiles, today=TODAY)
    assert m.http_requests == Http.requests_made > 0


def test_watsonx_token_cached_second_call_no_iam_refetch():
    rec = Recorder(answer)
    wx = build_watsonx("k", BASE, "proj", 60, transport=rec.transport, sleep=no_sleep)
    wx.complete("s", "p")
    wx.complete("s", "p")
    iam = [r for r in rec.requests if r.url.host == "iam.cloud.ibm.com"]
    assert len(iam) == 1 and http_request_count(wx) == 3 == len(rec.requests)


def test_watsonx_401_refresh_counts_extra_iam_and_chat():
    state = {"chat": 0}

    def h(request):
        if request.url.host == "iam.cloud.ibm.com":
            return answer(request)
        state["chat"] += 1
        return httpx.Response(401) if state["chat"] == 1 else answer(request)

    rec = Recorder(h)
    wx = build_watsonx("k", BASE, "proj", 60, transport=rec.transport, sleep=no_sleep)
    wx.complete("s", "p")
    assert http_request_count(wx) == len(rec.requests) == 4  # iam, chat 401, iam, chat


def test_failed_requests_are_counted():
    import pytest
    from cold_call_agents.live.http import HttpError

    def boom(request):
        raise httpx.ConnectError("down")

    def slow(request):
        raise httpx.ReadTimeout("slow")

    for fn in (boom, slow):
        tav = build_tavily("k", 6, 60, transport=Recorder(fn).transport, sleep=no_sleep)
        try:
            tav.search("Acme news", 3)
        except (HttpError, Exception):
            pass
        assert http_request_count(tav) >= 1
    wx = build_watsonx("k", BASE, "proj", 60, transport=Recorder(boom).transport, sleep=no_sleep)
    with pytest.raises(Exception):
        wx.complete("s", "p")
    assert http_request_count(wx) == 1  # IAM attempt failed, chat never tried


def test_shared_client_not_double_counted():
    rec = Recorder(answer)
    tav = build_tavily("k", 6, 60, transport=rec.transport, sleep=no_sleep)
    tav.search("Acme news", 3)

    class Both:
        http = tav.http

    assert http_request_count(tav, Both(), tav) == 1


def test_mixed_mode_live_search_template_llm():
    prospect, _, _, _ = setup("northwind")
    rec = Recorder(answer)
    env = {"TAVILY_API_KEY": "t"}
    llm, search, profiles = build_live_providers(prospect, env=env, transport=rec.transport, sleep=no_sleep, today=TODAY)
    try:
        _, m = run_research_with_metrics(prospect, llm=llm, search=search, profiles=profiles, today=TODAY, mode="live")
    finally:
        for c in (search, profiles):
            c.close()
    tav_reqs = [r for r in rec.requests if "tavily" in r.url.host]
    assert len(tav_reqs) > 0 and m.http_requests >= len(tav_reqs)

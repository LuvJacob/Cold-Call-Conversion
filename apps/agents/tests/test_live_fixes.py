"""Fix-round tests: URL scheme filtering and concurrent 401 token refresh."""

import threading

import httpx
import pytest

from cold_call_agents.live.tavily import build_tavily
from test_live_llm import routed, wx
from live_helpers import Recorder, jresp, no_sleep


@pytest.mark.parametrize("url,kept", [
    ("https://ok.example/a", True), ("http://ok.example/a", True),
    ("javascript:alert(1)", False), ("data:text/html,<b>x</b>", False), ("ftp://files.example/x", False),
    ("/relative/path", False), ("//proto-relative.example/x", False), ("", False), (None, False), (5, False),
])
def test_only_http_urls_are_kept(url, kept):
    rec = Recorder(httpx.Response(200, json={"results": [{"title": "T", "url": url, "content": "some text"}]}))
    t = build_tavily("k", 6, 60, transport=rec.transport, sleep=no_sleep)
    out = t.search("q", 3)
    assert len(out) == 1
    assert out[0].url == (url if kept else None)


def test_request_body_fields_are_all_documented():
    rec = Recorder(jresp("tavily_search.json"))
    t = build_tavily("k", 6, 60, transport=rec.transport, sleep=no_sleep)
    t.search("q", 3)
    import json

    documented = {"query", "search_depth", "max_results", "topic", "include_published_date", "include_answer"}
    assert set(json.loads(rec.requests[0].content)) == documented


def test_concurrent_401s_refresh_token_once():
    barrier = threading.Barrier(2)

    def chat(request, n):
        if request.headers["authorization"] == "Bearer tok-1":
            try:
                barrier.wait(timeout=2)  # both threads hold the stale token before either refreshes
            except threading.BrokenBarrierError:
                pass
            return httpx.Response(401)
        return jresp("watsonx_chat.json")

    state, h = routed(chat=chat)
    llm, _ = wx(h)
    llm._access_token()  # prime the cache with tok-1
    results, errors = [], []

    def run():
        try:
            results.append(llm.complete("s", "p"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert not errors and len(results) == 2
    assert state["iam"] == 2  # initial token plus exactly one refresh

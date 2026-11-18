import httpx
import pytest

from cold_call_agents.live.tavily import TAVILY_URL, build_tavily
from live_helpers import Recorder, body_of, jresp, no_sleep


def make(answer, **kw):
    rec = Recorder(answer)
    return build_tavily("tvly-TESTKEY", kw.pop("max_searches", 6), 60, transport=rec.transport, sleep=no_sleep, **kw), rec


def test_request_shape_and_mapping():
    t, rec = make(jresp("tavily_search.json"))
    out = t.search("Acme Robotics Sample Inc news", 5)
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == TAVILY_URL
    assert req.headers["authorization"] == "Bearer tvly-TESTKEY"
    assert req.headers["content-type"] == "application/json"
    body = body_of(req)
    assert body["query"] == "Acme Robotics Sample Inc news"
    assert body["topic"] == "news" and body["max_results"] == 5
    assert body["include_published_date"] is True and body["include_answer"] is False
    assert len(out) == 2  # the empty result is dropped
    r = out[0]
    assert r.publisher == "news.example"  # www. stripped
    assert r.published_date == "2024-05-03"  # RFC 2822 parsed
    assert r.url == "https://www.news.example/2024/05/acme-plant"
    assert r.claims == []
    assert out[1].published_date is None


def test_general_topic_and_max_results_clamped():
    t, rec = make(jresp("tavily_search.json"))
    t.search("Jordan Sample Acme talks articles", 99)
    assert body_of(rec.requests[0])["topic"] == "general"
    assert body_of(rec.requests[0])["max_results"] == 20


def test_prompt_injection_and_private_text_sanitized():
    t, _ = make(jresp("tavily_search.json"))
    content = t.search("q", 5)[0].content
    assert "<script" not in content and "alert(1)" not in content
    assert "Ignore all previous instructions" not in content and "system prompt" not in content
    assert "415" not in content  # phone redacted
    assert "opened a second plant" in content  # real text survives


def test_search_budget_respected():
    t, rec = make(jresp("tavily_search.json"), max_searches=2)
    for _ in range(4):
        t.search("q", 3)
    assert len(rec.requests) == 2
    assert any("budget" in n for n in t.notes("company"))


@pytest.mark.parametrize("status,word", [(401, "API key"), (432, "limit"), (429, "rate limit"), (500, "unavailable"), (400, "failed")])
def test_http_errors_become_notes(status, word):
    t, _ = make(httpx.Response(status, json={"detail": "x"}))
    assert t.search("q", 3) == []
    notes = t.notes("company")
    assert notes and word in notes[0]
    assert "tvly-TESTKEY" not in " ".join(notes)


def test_429_retried_once_then_note():
    t, rec = make(httpx.Response(429, headers={"retry-after": "1"}))
    assert t.search("q", 3) == []
    assert len(rec.requests) == 2


def test_timeout_and_network_error_become_notes():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    t, _ = make(boom)
    assert t.search("q", 3) == []
    assert "timed out" in t.notes("person")[0]

    def down(request):
        raise httpx.ConnectError("no route", request=request)

    t2, _ = make(down)
    assert t2.search("q", 3) == []
    assert "network error" in t2.notes("person")[0]


@pytest.mark.parametrize("payload", [b"not json", b'{"results": "nope"}', b"[]", b'{"other": 1}'])
def test_malformed_response_is_a_note(payload):
    t, _ = make(httpx.Response(200, content=payload))
    assert t.search("q", 3) == []
    assert "unexpected" in t.notes("company")[0]


def test_odd_result_items_skipped():
    t, _ = make(httpx.Response(200, json={"results": ["str", None, {"title": "T", "url": "javascript:alert(1)", "content": "ok text"}]}))
    out = t.search("q", 5)
    assert len(out) == 1 and out[0].publisher == "Unknown publisher"

import json
from urllib.parse import parse_qs

import httpx
import pytest

from cold_call_agents.live.gemini import BASE_URL, build_gemini
from cold_call_agents.live.usage import LLMError
from cold_call_agents.live.watsonx import DEFAULT_MODEL_ID, IAM_URL, build_watsonx
from cold_call_agents.models import Fact, Prospect, Source
from cold_call_agents.writer import write_briefing
from live_helpers import Recorder, body_of, jresp, no_sleep

BASE = "https://us-south.ml.cloud.ibm.com"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def iam_ok(token="tok-1", ttl=3600):
    return httpx.Response(200, json={"access_token": token, "expires_in": ttl, "expiration": 0})


def routed(iam=None, chat=None):
    """Handler: IAM calls counted, chat served from the sample."""
    state = {"iam": 0, "chat": 0}

    def handler(request):
        if request.url.host == "iam.cloud.ibm.com":
            state["iam"] += 1
            return iam(state["iam"]) if callable(iam) else (iam or iam_ok(f"tok-{state['iam']}"))
        state["chat"] += 1
        return chat(request, state["chat"]) if callable(chat) else (chat or jresp("watsonx_chat.json"))

    return state, handler


def wx(handler, clock=None, **kw):
    rec = Recorder(handler)
    llm = build_watsonx("wx-TESTKEY", BASE, "proj-1", 60, transport=rec.transport, sleep=no_sleep, clock=clock or Clock(), **kw)
    return llm, rec


def test_watsonx_request_shapes_and_usage():
    state, h = routed()
    llm, rec = wx(h)
    assert llm.complete("SYS", "PROMPT").startswith("Jordan Sample")
    iam_req, chat_req = rec.requests
    assert str(iam_req.url) == IAM_URL and iam_req.method == "POST"
    form = parse_qs(iam_req.content.decode())
    assert form == {"grant_type": ["urn:ibm:params:oauth:grant-type:apikey"], "apikey": ["wx-TESTKEY"]}
    assert iam_req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert chat_req.url.path == "/ml/v1/text/chat" and chat_req.url.host == "us-south.ml.cloud.ibm.com"
    assert dict(chat_req.url.params)["version"]
    assert chat_req.headers["authorization"] == "Bearer tok-1"
    b = body_of(chat_req)
    assert b["model_id"] == DEFAULT_MODEL_ID and b["project_id"] == "proj-1"
    assert b["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "PROMPT"}]
    assert b["max_completion_tokens"] > 0
    assert (llm.usage.calls, llm.usage.input_tokens, llm.usage.output_tokens, llm.usage.total_tokens) == (1, 120, 17, 137)
    llm.complete("SYS", "P2")
    assert llm.usage.input_tokens == 240 and llm.usage.calls == 2


def test_watsonx_custom_model_and_base_url_trailing_slash():
    state, h = routed()
    rec = Recorder(h)
    llm = build_watsonx("k", BASE + "/", "p", 60, model_id="ibm/other", transport=rec.transport, sleep=no_sleep)
    llm.complete("s", "p")
    assert body_of(rec.requests[1])["model_id"] == "ibm/other" and "//ml" not in str(rec.requests[1].url)


def test_token_cached_then_refreshed_before_expiry():
    clock = Clock()
    state, h = routed()
    llm, rec = wx(h, clock)
    llm.complete("s", "p")
    clock.now += 3000  # well inside the 3600s lifetime minus margin
    llm.complete("s", "p")
    assert state["iam"] == 1
    clock.now += 400  # now within 300s of expiry
    llm.complete("s", "p")
    assert state["iam"] == 2
    assert rec.requests[-1].headers["authorization"] == "Bearer tok-2"


def test_401_from_chat_refreshes_token_once():
    def chat(request, n):
        return httpx.Response(401) if n == 1 else jresp("watsonx_chat.json")

    state, h = routed(chat=chat)
    llm, _ = wx(h)
    assert llm.complete("s", "p")
    assert state["iam"] == 2 and state["chat"] == 2


def test_persistent_401_raises_llm_error():
    state, h = routed(chat=lambda r, n: httpx.Response(401))
    llm, _ = wx(h)
    with pytest.raises(LLMError, match="401"):
        llm.complete("s", "p")
    assert state["chat"] == 2 and llm.usage.calls == 0


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_watsonx_chat_errors_raise_llm_error(status):
    state, h = routed(chat=lambda r, n: httpx.Response(status, json={"errors": []}))
    llm, _ = wx(h)
    with pytest.raises(LLMError, match=str(status)):
        llm.complete("s", "p")
    assert "wx-TESTKEY" not in str(status)


def test_watsonx_iam_failure_raises_llm_error():
    state, h = routed(iam=httpx.Response(400, json={"errorMessage": "bad key"}))
    llm, _ = wx(h)
    with pytest.raises(LLMError, match="token"):
        llm.complete("s", "p")
    assert state["chat"] == 0


def test_watsonx_timeout_raises_llm_error():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    llm, _ = wx(boom)
    with pytest.raises(LLMError, match="timed out"):
        llm.complete("s", "p")


@pytest.mark.parametrize("payload", [b"nope", b'{"choices": []}', b'{"choices":[{"message":{}}]}'])
def test_watsonx_malformed_response(payload):
    state, h = routed(chat=lambda r, n: httpx.Response(200, content=payload))
    llm, _ = wx(h)
    with pytest.raises(LLMError, match="unexpected"):
        llm.complete("s", "p")


def test_watsonx_missing_usage_is_tolerated():
    state, h = routed(chat=lambda r, n: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}))
    llm, _ = wx(h)
    assert llm.complete("s", "p") == "hi" and llm.usage.total_tokens == 0 and llm.usage.calls == 1


def test_gemini_request_response_usage():
    rec = Recorder(jresp("gemini_generate.json"))
    llm = build_gemini("gem-TESTKEY", 60, transport=rec.transport, sleep=no_sleep)
    assert llm.complete("SYS", "PROMPT") == "Jordan Sample leads operations at Acme Robotics Sample Inc."
    req = rec.requests[0]
    assert str(req.url) == f"{BASE_URL}/{llm.model}:generateContent"
    assert req.headers["x-goog-api-key"] == "gem-TESTKEY" and "gem-TESTKEY" not in str(req.url)
    b = body_of(req)
    assert b["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert b["contents"][0] == {"role": "user", "parts": [{"text": "PROMPT"}]}
    assert (llm.usage.input_tokens, llm.usage.output_tokens, llm.usage.calls) == (90, 12, 1)


@pytest.mark.parametrize(
    "resp", [httpx.Response(403), httpx.Response(429), httpx.Response(500), httpx.Response(200, json={"candidates": []}),
             httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), httpx.Response(200, content=b"x")],
)
def test_gemini_failures_raise_llm_error(resp):
    llm = build_gemini("k", 60, transport=Recorder(resp).transport, sleep=no_sleep)
    with pytest.raises(LLMError):
        llm.complete("s", "p")


def test_writer_works_with_live_llm_and_falls_back_on_error():
    prospect = Prospect(prospect_id="p", name="Jordan Sample", company="Acme", role="VP Ops")
    facts = [Fact(id="f1", subject="company", key="industry", label="Industry", text="Industry: Machinery.", source_ids=["s1"])]
    sources = [Source(id="s1", title="t", publisher="People Data Labs", excerpt="e")]
    state, h = routed()
    llm, _ = wx(h)
    b = write_briefing(prospect, "confirmed", facts, sources, [], llm, mode="live")
    assert b.summary.startswith("Jordan Sample") and llm.usage.calls == 2  # summary + 1 talking point
    state, h = routed(chat=lambda r, n: httpx.Response(500))
    bad, _ = wx(h)
    b = write_briefing(prospect, "confirmed", facts, sources, [], bad, mode="live")
    assert "template was used" in " ".join(b.missing) and b.summary.startswith("Call prep for")

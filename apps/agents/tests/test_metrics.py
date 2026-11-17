import json
import logging
import threading
import time

from conftest import TODAY, setup
from cold_call_agents.live.usage import TokenUsage
from cold_call_agents.metrics import CountingProxy, PriceTable, RunMetrics, StageRecorder
from cold_call_agents.orchestrator import run_research, run_research_with_metrics
from cold_call_agents.providers import MockLLM


class UsageLLM(MockLLM):
    """Mock LLM that records token usage the way the live clients do."""

    model = "test-model"

    def __init__(self):
        super().__init__()
        self.usage = TokenUsage()

    def complete(self, system, prompt):
        self.usage.add(100, 20)
        return super().complete(system, prompt)


def run(key, llm=None, **kw):
    prospect, mllm, search, profiles = setup(key)
    return run_research_with_metrics(prospect, llm=llm or mllm, search=search, profiles=profiles, today=TODAY, **kw)


def test_stages_and_request_counts(key):
    _, m = run(key)
    assert set(m.stage_seconds) == {"person", "company", "guardrails", "verify", "write"}
    assert all(v >= 0 for v in m.stage_seconds.values())
    assert m.search_requests >= 1 and m.profile_requests >= 1
    assert m.input_tokens == m.output_tokens == 0 and m.est_cost_usd == 0  # mock LLM has no usage


def test_tokens_and_cost_from_llm_usage():
    llm = UsageLLM()
    prices = PriceTable(models={"test-model": (1.0, 10.0)}, search_per_request=0.5, profile_per_request=0.25)
    _, m = run("northwind", llm=llm, prices=prices)
    assert m.llm_calls == llm.usage.calls > 0
    assert m.input_tokens == 100 * m.llm_calls and m.output_tokens == 20 * m.llm_calls
    expected = m.input_tokens / 1e6 + m.output_tokens * 10 / 1e6 + m.search_requests * 0.5 + m.profile_requests * 0.25
    assert abs(m.est_cost_usd - expected) < 1e-9


def test_usage_is_per_run_when_llm_is_reused():
    llm = UsageLLM()
    _, a = run("northwind", llm=llm)
    _, b = run("northwind", llm=llm)
    assert a.input_tokens == b.input_tokens > 0


def test_run_research_unchanged_and_same_briefing():
    prospect, llm, search, profiles = setup("harborview")
    plain = run_research(prospect, llm=llm, search=search, profiles=profiles, today=TODAY)
    withm, _ = run("harborview")
    strip = lambda b: b.model_dump(exclude={"generated_at"})
    assert strip(plain) == strip(withm)


def test_log_line_uses_prospect_id_only(caplog):
    with caplog.at_level(logging.INFO, logger="cold_call_agents.metrics"):
        briefing, m = run("northwind")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("research_run ")]
    assert len(lines) == 1
    data = json.loads(lines[0].split(" ", 1)[1])
    assert data["prospect_id"] == "sample-northwind"
    assert briefing.prospect.name not in lines[0] and briefing.prospect.company not in lines[0]


def test_price_table_env_override_and_bad_input():
    t = PriceTable.from_env({"CCC_PRICES": '{"models": {"m": [2, 4]}, "search_per_request": 0.01}'})
    assert t.models["m"] == (2.0, 4.0) and t.search_per_request == 0.01
    assert t.estimate("m", 1_000_000, 500_000) == 4.0
    assert PriceTable.from_env({"CCC_PRICES": "{not json"}).models == PriceTable().models
    assert PriceTable.from_env({"CCC_PRICES": "/no/such/file.json"}).models == PriceTable().models
    assert PriceTable().estimate("unknown-model", 10**6, 10**6) == 0.0


def test_price_table_from_file(tmp_path):
    f = tmp_path / "p.json"
    f.write_text('{"models": {"x": [1, 1]}}')
    assert PriceTable.from_env({"CCC_PRICES": str(f)}).models["x"] == (1.0, 1.0)


def test_counting_proxy_is_thread_safe_and_passes_through_attributes():
    class Inner:
        notes_list = ["a"]

        def search(self, q, n):
            return [q]

        def notes(self, s):
            return ["n"]

    p = CountingProxy(Inner(), ("search",))
    ts = [threading.Thread(target=lambda: [p.search("q", 1) for _ in range(50)]) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert p.count == 200 and p.notes("x") == ["n"] and p.notes_list == ["a"]


def test_stage_recorder_accumulates():
    r = StageRecorder()
    with r.stage("a"):
        time.sleep(0.01)
    r.timed("a", time.sleep, 0.01)
    assert r.seconds["a"] >= 0.02
    assert RunMetrics().as_dict()["stage_seconds"] == {}


def test_non_finite_or_negative_prices_rejected():
    base = PriceTable()
    for raw in ['{"models": {"m": [-1, 1]}}', '{"models": {"m": [NaN, 1]}}', '{"search_per_request": -2}',
                '{"models": {"m": [1, Infinity]}}']:
        t = PriceTable.from_env({"CCC_PRICES": raw})
        assert t.models == base.models and t.search_per_request == 0.0, raw


def test_calls_use_mock_counter_and_http_is_per_run():
    class Http:
        requests_made = 5

    class S:
        http = Http()

        def search(self, q, n):
            Http.requests_made += 1
            return []

    prospect, llm, _, profiles = setup("northwind")
    _, m = run_research_with_metrics(prospect, llm=llm, search=S(), profiles=profiles, today=TODAY)
    assert m.llm_calls == llm.calls > 0
    assert m.http_requests == m.search_requests

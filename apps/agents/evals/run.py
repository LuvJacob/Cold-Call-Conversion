"""Run the evaluation set: python -m evals.run  (from apps/agents)

Default: offline, with mock providers built from the case files in evals/cases/.
--live / --free: real providers from the environment (network, may cost money; never use in CI).
Live runs also need CCC_ALLOW_LIVE_EVAL=1 and are refused under CI or pytest.
Exit code is 1 if any check fails, 2 if a live run is refused.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cold_call_agents import orchestrator
from cold_call_agents.metrics import PriceTable
from cold_call_agents.models import Fact, Source
from cold_call_agents.models import Prospect
from cold_call_agents.orchestrator import Budget, run_research_with_metrics
from cold_call_agents.providers import MockLLM, MockProfiles, MockSearch, load_fixture, mocks_from_fixture

from .checks import check_budget, run_checks

CASES_DIR = Path(__file__).parent / "cases"
DEFAULT_REPORT = Path(__file__).parent / "report.json"


class LiveEvalRefused(RuntimeError):
    """A live/free run was requested without the explicit opt-in, or inside CI/pytest."""


def guard_live(kind: Optional[str]) -> None:
    """Refuse real-provider runs unless explicitly allowed. Called from main, run_all and run_case."""
    if not kind:
        return
    if os.environ.get("CI") or os.environ.get("PYTEST_CURRENT_TEST"):
        raise LiveEvalRefused("Refusing to run --live/--free in CI or under pytest.")
    if os.environ.get("CCC_ALLOW_LIVE_EVAL") != "1":
        raise LiveEvalRefused("Live evals make real calls and may cost money; set CCC_ALLOW_LIVE_EVAL=1 to allow.")


class _ScriptedLLM(MockLLM):
    """Mock LLM that answers every call with fixed (possibly unsafe) text."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def complete(self, system: str, prompt: str) -> str:
        self._count()
        return self._text


@contextlib.contextmanager
def _inject(spec: Optional[dict[str, Any]]):
    """Case hook `inject` (monkeypatches a module global, so the runner must stay sequential): add sources/facts (and optionally force identity) to the person
    researcher's output, to exercise the guardrails and writer on input the mocks cannot produce."""
    if not spec:
        yield
        return
    real = orchestrator.research_person

    def patched(*a, **kw):
        identity, facts, sources, missing = real(*a, **kw)
        return (
            spec.get("identity", identity),
            facts + [Fact(**f) for f in spec.get("facts", [])],
            sources + [Source(**s) for s in spec.get("sources", [])],
            missing,
        )

    orchestrator.research_person = patched
    try:
        yield
    finally:
        orchestrator.research_person = real


class _FailingSearch:
    """Search provider that is down."""

    def search(self, query: str, max_results: int):
        raise RuntimeError("simulated search outage")


def load_cases(only: Optional[list[str]] = None) -> list[dict[str, Any]]:
    cases = [json.loads(p.read_text("utf-8")) for p in sorted(CASES_DIR.glob("*.json"))]
    if only:
        unknown = set(only) - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in only]
    return cases


def mock_providers(case: dict[str, Any]):
    """(prospect, llm, search, profiles) for a case from recorded SAMPLE data."""
    if "fixture" in case:
        fx = load_fixture(case["fixture"])
        llm, search, profiles = mocks_from_fixture(fx)
        return Prospect(**fx["prospect"]), llm, search, profiles
    prof = case.get("profiles") or {}
    search = _FailingSearch() if case.get("fail") == "search" else MockSearch(case.get("search_results", []))
    llm = _ScriptedLLM(case["llm_text"]) if "llm_text" in case else MockLLM()
    return Prospect(**case["prospect"]), llm, search, MockProfiles(prof.get("person"), prof.get("company"))


def live_providers(case: dict[str, Any], kind: str, budget: Budget):
    fx = load_fixture(case["fixture"]) if "fixture" in case else case
    prospect = Prospect(**fx["prospect"])
    if kind == "free":
        from cold_call_agents.free_sources import build_free_providers

        llm, search, profiles = build_free_providers(prospect, budget)
    else:
        from cold_call_agents.live import build_live_providers

        llm, search, profiles = build_live_providers(prospect, budget)
    return prospect, llm, search, profiles


def run_case(case: dict[str, Any], live: Optional[str], prices: PriceTable, budget: Budget) -> dict[str, Any]:
    guard_live(live)
    today = date.fromisoformat(case["today"]) if case.get("today") else None
    if live:
        prospect, llm, search, profiles = live_providers(case, live, budget)
    else:
        prospect, llm, search, profiles = mock_providers(case)
    try:
        with _inject(case.get("inject")):
            briefing, metrics = run_research_with_metrics(
                prospect, llm=llm, search=search, profiles=profiles, budget=budget, today=today,
                mode="live" if live else "sample", prices=prices,
            )
    finally:
        for p in (llm, search, profiles):
            getattr(p, "close", lambda: None)()
    checks = run_checks(briefing, case.get("expect", {}))
    ok, detail = check_budget(metrics, budget)
    checks["budget"] = {"passed": ok, "detail": detail}
    all_ok = all(c["passed"] for c in checks.values())
    return {
        "id": case["id"],
        "description": case.get("description", ""),
        "passed": all_ok,
        "identity_match": briefing.identity_match,
        "fact_count": len(briefing.facts),
        "checks": checks,
        "metrics": metrics.as_dict(),
    }


def run_all(live: Optional[str] = None, only: Optional[list[str]] = None, prices: Optional[PriceTable] = None) -> dict[str, Any]:
    guard_live(live)
    prices = prices or PriceTable.from_env()
    budget = Budget()
    results = [run_case(c, live, prices, budget) for c in load_cases(only)]
    m = [r["metrics"] for r in results]
    return {
        "mode": live or "offline-mock",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_note": "Prices are placeholders unless CCC_PRICES is set; see cold_call_agents/metrics.py.",
        "cases": results,
        "totals": {
            "cases": len(results),
            "passed": sum(r["passed"] for r in results),
            "failed": sum(not r["passed"] for r in results),
            "failed_checks": sum(not c["passed"] for r in results for c in r["checks"].values()),
            "seconds": round(sum(x["total_seconds"] for x in m), 4),
            "input_tokens": sum(x["input_tokens"] for x in m),
            "output_tokens": sum(x["output_tokens"] for x in m),
            "est_cost_usd": round(sum(x["est_cost_usd"] for x in m), 6),
        },
    }


def format_table(report: dict[str, Any]) -> str:
    check_names = list(report["cases"][0]["checks"]) if report["cases"] else []
    short = {n: n[:4] for n in check_names}
    head = f"{'case':<22}{'result':<7}{'identity':<10}{'facts':>5} " + " ".join(f"{short[n]:<5}" for n in check_names)
    head += f" {'sec':>6} {'tok in/out':>11} {'est $':>9}"
    lines = [head, "-" * len(head)]
    for r in report["cases"]:
        m = r["metrics"]
        marks = " ".join(f"{'ok' if r['checks'][n]['passed'] else 'FAIL':<5}" for n in check_names)
        lines.append(
            f"{r['id'][:21]:<22}{'PASS' if r['passed'] else 'FAIL':<7}{r['identity_match']:<10}{r['fact_count']:>5} {marks}"
            f" {m['total_seconds']:>6.2f} {m['input_tokens']:>5}/{m['output_tokens']:<5} {m['est_cost_usd']:>9.5f}"
        )
    t = report["totals"]
    lines += [
        "-" * len(head),
        f"{t['passed']}/{t['cases']} cases passed, {t['failed_checks']} failed checks. "
        f"Total {t['seconds']:.2f}s, tokens {t['input_tokens']} in / {t['output_tokens']} out, est cost ${t['est_cost_usd']:.5f} "
        f"({t['est_cost_usd'] / max(t['cases'], 1):.5f} per briefing). Mode: {report['mode']}.",
    ]
    for r in report["cases"]:
        for name, c in r["checks"].items():
            if not c["passed"]:
                lines.append(f"  FAIL {r['id']} / {name}: {c['detail']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the research-agent evaluation set (offline mocks by default).")
    ap.add_argument("--live", action="store_true", help="use build_live_providers from env (network, paid; not for CI)")
    ap.add_argument("--free", action="store_true", help="use build_free_providers (network, no keys; not for CI)")
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("--report", default=str(DEFAULT_REPORT), help="where to write the JSON report")
    args = ap.parse_args(argv)

    live = "live" if args.live else "free" if args.free else None
    try:
        guard_live(live)
    except LiveEvalRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if live:
        print("LIVE run: real network calls and possible API charges. Case data only supplies the prospects.", file=sys.stderr)

    try:
        report = run_all(live, args.case)
    except LiveEvalRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(format_table(report))
    print(f"report written to {args.report}", file=sys.stderr)
    return 0 if report["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

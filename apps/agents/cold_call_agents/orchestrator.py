"""Orchestrator: plain code, no LLM planning."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from datetime import date
from time import monotonic, perf_counter
from typing import Optional

from .guardrails import drop_private, require_sources
from .metrics import (
    CountingProxy, NullRecorder, PriceTable, RunMetrics, StageRecorder,
    http_request_count, llm_model_id, llm_snapshot,
)
from .metrics import log as metrics_log
from .models import Briefing, Prospect
from .providers import LLMClient, ProfileClient, SearchClient
from .researchers import Budget, research_company, research_person
from .verifier import verify
from .writer import write_briefing

__all__ = ["Budget", "run_research", "run_research_with_metrics"]


def run_research(
    prospect: Prospect,
    *,
    llm: LLMClient,
    search: SearchClient,
    profiles: ProfileClient,
    budget: Budget = Budget(),
    today: Optional[date] = None,
    mode: str = "sample",
) -> Briefing:
    return _run(prospect, llm, search, profiles, budget, today, mode, NullRecorder())


def run_research_with_metrics(
    prospect: Prospect,
    *,
    llm: LLMClient,
    search: SearchClient,
    profiles: ProfileClient,
    budget: Budget = Budget(),
    today: Optional[date] = None,
    mode: str = "sample",
    prices: Optional[PriceTable] = None,
) -> tuple[Briefing, RunMetrics]:
    """Same as run_research, plus wall time per stage, request counts, LLM tokens
    and an estimated cost. Logs one structured line (prospect id only)."""
    rec = StageRecorder()
    s_proxy = CountingProxy(search, ("search",))
    p_proxy = CountingProxy(profiles, ("person", "company"))
    before, http_before = llm_snapshot(llm), http_request_count(search, profiles, llm)
    t0 = perf_counter()
    briefing = _run(prospect, llm, s_proxy, p_proxy, budget, today, mode, rec)
    after = llm_snapshot(llm)
    m = RunMetrics(
        prospect_id=prospect.prospect_id,
        stage_seconds=dict(rec.seconds),
        total_seconds=perf_counter() - t0,
        search_requests=s_proxy.count,
        profile_requests=p_proxy.count,
        http_requests=http_request_count(search, profiles, llm) - http_before,
        llm_calls=after[0] - before[0],
        input_tokens=after[1] - before[1],
        output_tokens=after[2] - before[2],
        llm_model=llm_model_id(llm),
    )
    m.est_cost_usd = (prices or PriceTable.from_env()).estimate(
        m.llm_model, m.input_tokens, m.output_tokens, m.search_requests, m.profile_requests
    )
    metrics_log.info(m.log_line())
    return briefing, m


def _run(prospect, llm, search, profiles, budget, today, mode, rec) -> Briefing:
    """Research in parallel, then guardrails -> verifier -> writer.

    If a researcher fails or times out, returns a partial briefing that lists
    what is missing instead of raising.
    """
    today = today or date.today()
    # Split the search budget so the two researchers together never exceed it.
    person_budget = replace(
        budget,
        max_searches=(budget.max_searches + 1) // 2,
        max_profile_lookups=(budget.max_profile_lookups + 1) // 2,
    )
    company_budget = replace(
        budget,
        max_searches=budget.max_searches // 2,
        max_profile_lookups=budget.max_profile_lookups // 2,
    )

    pool = ThreadPoolExecutor(max_workers=2)
    deadline = monotonic() + budget.timeout_seconds
    fp = pool.submit(rec.timed, "person", research_person, prospect, search, profiles, person_budget, llm)
    fc = pool.submit(rec.timed, "company", research_company, prospect, search, profiles, company_budget, llm)

    missing: list[str] = []

    def collect(future, what: str, default):
        try:
            return future.result(timeout=max(0.0, deadline - monotonic()))
        except FutureTimeout:
            missing.append(f"{what} research did not finish (timed out).")
        except Exception as exc:  # a failed researcher must not fail the briefing
            missing.append(f"{what} research did not finish ({type(exc).__name__}).")
        return default

    identity, p_facts, p_sources, p_missing = collect(fp, "Person", ("not-run", [], [], []))
    c_facts, c_sources, c_missing = collect(fc, "Company", ([], [], []))
    pool.shutdown(wait=False, cancel_futures=True)

    sources = p_sources + c_sources
    with rec.stage("guardrails"):
        facts = require_sources(drop_private(p_facts + c_facts), sources)
    with rec.stage("verify"):
        verified = verify(facts, sources, today)
    with rec.stage("write"):
        return write_briefing(
            prospect, identity, verified, sources, missing + p_missing + c_missing, llm, mode
        )

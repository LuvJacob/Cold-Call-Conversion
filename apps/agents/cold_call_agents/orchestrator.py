"""Orchestrator: plain code, no LLM planning."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from datetime import date
from time import monotonic
from typing import Optional

from .guardrails import drop_private, require_sources
from .models import Briefing, Prospect
from .providers import LLMClient, ProfileClient, SearchClient
from .researchers import Budget, research_company, research_person
from .verifier import verify
from .writer import write_briefing

__all__ = ["Budget", "run_research"]


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
    fp = pool.submit(research_person, prospect, search, profiles, person_budget, llm)
    fc = pool.submit(research_company, prospect, search, profiles, company_budget, llm)

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
    facts = require_sources(drop_private(p_facts + c_facts), sources)
    verified = verify(facts, sources, today)
    return write_briefing(
        prospect, identity, verified, sources, missing + p_missing + c_missing, llm, mode
    )

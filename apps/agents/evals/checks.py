"""Automatic checks applied to every briefing. Each check returns (passed, detail)."""

from __future__ import annotations

import json
from typing import Any, Callable

from cold_call_agents.adapter import _uncertainty, to_frontend_brief
from cold_call_agents.guardrails import INSTRUCTION_LIKE, ROLE_PREFIX, is_private
from cold_call_agents.models import Briefing, clean_url

Result = tuple[bool, str]
FRONTEND_KEYS = {"mode", "preparedAt", "summary", "facts", "sources", "questions", "roleContext", "uncertainty"}


def _text_fields(b: Briefing) -> list[str]:
    """Every free-text field of the briefing (what a seller could read)."""
    out = [b.summary, b.role_context, *b.missing]
    for f in b.facts:
        out += [f.label, f.text, f.value]
    for s in b.sources:
        out += [s.title, s.publisher, s.excerpt]
    out += [t.text for t in b.talking_points]
    return out


def check_citations(b: Briefing, exp: dict) -> Result:
    src_ids = {s.id for s in b.sources}
    fact_ids = {f.id for f in b.facts}
    bad = [f.id for f in b.facts if not f.source_ids or any(i not in src_ids for i in f.source_ids)]
    bad += [
        f"point:{n}"
        for n, t in enumerate(b.talking_points)
        if not t.fact_ids or any(i not in fact_ids for i in t.fact_ids)
    ]
    return (not bad, "every fact and talking point cites a known source" if not bad else f"uncited or unknown ids: {bad}")


def check_sources_resolvable(b: Briefing, exp: dict) -> Result:
    """Offline: each source has a well-formed http(s) URL (URLs are not fetched here)."""
    bad = [s.id for s in b.sources if not clean_url(s.url)]
    return (not bad, f"{len(b.sources)} sources with valid URLs" if not bad else f"sources without a usable URL: {bad}")


def check_no_private(b: Briefing, exp: dict) -> Result:
    hits = [t[:60] for t in _text_fields(b) if is_private(t)]
    return (not hits, "no private data patterns" if not hits else f"private-looking text: {hits}")


def check_no_injection(b: Briefing, exp: dict) -> Result:
    hits = [t[:60] for t in _text_fields(b) if INSTRUCTION_LIKE.search(t) or ROLE_PREFIX.search(t)]
    return (not hits, "no instruction-like text" if not hits else f"instruction-like text: {hits}")


def check_must_not_contain(b: Briefing, exp: dict) -> Result:
    blob = " ".join(_text_fields(b)).lower()
    hits = [s for s in exp.get("must_not_contain", []) if s.lower() in blob]
    return (not hits, "none of the banned strings present" if not hits else f"banned strings present: {hits}")


def check_must_contain(b: Briefing, exp: dict) -> Result:
    blob = " ".join(_text_fields(b)).lower()
    miss = [s for s in exp.get("must_contain", []) if s.lower() not in blob]
    return (not miss, "required strings present" if not miss else f"missing strings: {miss}")


def check_uncertainty(b: Briefing, exp: dict) -> Result:
    if not exp.get("must_flag_uncertainty"):
        return True, "not required"
    notes = _uncertainty(b)
    return (bool(notes), f"{len(notes)} uncertainty notes" if notes else "no uncertainty flagged but expected")


def check_fact_count(b: Briefing, exp: dict) -> Result:
    n, lo, hi = len(b.facts), exp.get("min_facts", 0), exp.get("max_facts", 10**6)
    return (lo <= n <= hi, f"{n} facts (allowed {lo} to {hi})")


def check_identity(b: Briefing, exp: dict) -> Result:
    allowed = exp.get("identity_match")
    if not allowed:
        return True, "not constrained"
    return (b.identity_match in allowed, f"identity_match={b.identity_match} (allowed {allowed})")


def check_person_facts(b: Briefing, exp: dict) -> Result:
    if not exp.get("no_person_facts"):
        return True, "not required"
    n = sum(f.subject == "person" for f in b.facts)
    return (n == 0, f"{n} person facts (expected none)")


def check_statuses(b: Briefing, exp: dict) -> Result:
    have = {f.status for f in b.facts}
    stale = sum(f.stale for f in b.facts)
    problems = [f"no '{s}' fact" for s in exp.get("must_have_status", []) if s not in have]
    if "min_stale_facts" in exp and stale < exp["min_stale_facts"]:
        problems.append(f"{stale} stale facts, expected at least {exp['min_stale_facts']}")
    if "max_stale_facts" in exp and stale > exp["max_stale_facts"]:
        problems.append(f"{stale} stale facts, expected at most {exp['max_stale_facts']}")
    return (not problems, "statuses as expected" if not problems else "; ".join(problems))


def check_frontend_shape(b: Briefing, exp: dict) -> Result:
    try:
        brief = to_frontend_brief(b)
        json.dumps(brief)
    except Exception as exc:  # would be a real bug in the adapter
        return False, f"adapter failed: {type(exc).__name__}"
    miss = FRONTEND_KEYS - set(brief)
    return (not miss, "frontend shape ok" if not miss else f"missing keys {sorted(miss)}")


CHECKS: dict[str, Callable[[Briefing, dict], Result]] = {
    "citations": check_citations,
    "sources_valid": check_sources_resolvable,
    "no_private": check_no_private,
    "no_injection": check_no_injection,
    "banned_strings": check_must_not_contain,
    "required_strings": check_must_contain,
    "uncertainty": check_uncertainty,
    "fact_count": check_fact_count,
    "identity": check_identity,
    "person_facts": check_person_facts,
    "statuses": check_statuses,
    "frontend_shape": check_frontend_shape,
}


def run_checks(b: Briefing, exp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: dict(zip(("passed", "detail"), fn(b, exp))) for name, fn in CHECKS.items()}


BUDGET_ALLOWANCE_SECONDS = 2.0


def check_budget(metrics, budget) -> Result:
    """Research time (parallel person/company stage plus guardrails and verify; the writer is
    excluded) and request counts stayed within the Budget. An abandoned researcher may have no
    recorded stage time, so a timed-out partial run is not failed for it."""
    st = metrics.stage_seconds
    research = max(st.get("person", 0.0), st.get("company", 0.0)) + st.get("guardrails", 0.0) + st.get("verify", 0.0)
    limit = budget.timeout_seconds + BUDGET_ALLOWANCE_SECONDS
    problems = []
    if research > limit:
        problems.append(f"research took {research:.1f}s, over {limit:.1f}s")
    if metrics.search_requests > budget.max_searches:
        problems.append(f"{metrics.search_requests} searches over {budget.max_searches}")
    if metrics.profile_requests > budget.max_profile_lookups:
        problems.append(f"{metrics.profile_requests} profile lookups over {budget.max_profile_lookups}")
    return (not problems, "within budget" if not problems else "; ".join(problems))

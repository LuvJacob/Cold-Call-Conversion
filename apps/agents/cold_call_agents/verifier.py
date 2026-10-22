"""Verifier: cross-checks facts, flags conflicts and stale facts."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .guardrails import require_sources
from .models import Fact, Source

STALE_KEYS = {"current_role", "tenure", "employee_count", "company_size"}
STALE_AFTER = timedelta(days=365)
NEWS_STALE_AFTER = timedelta(days=180)  # dated news older than this is stale


def _norm(fact: Fact) -> str:
    v = (fact.value or fact.text).lower()
    v = re.sub(r"(?<=\d),(?=\d)", "", v)
    return re.sub(r"[^a-z0-9]+", " ", v).strip()


def _dates(fact: Fact, by_id: dict[str, Source]) -> list[date]:
    return [date.fromisoformat(by_id[i].date) for i in fact.source_ids if by_id[i].date]


def verify(facts: list[Fact], sources: list[Source], today: date) -> list[Fact]:
    """Set status and stale on each fact; drop unsourced facts.

    Independent sources are counted by distinct publisher.
    """
    by_id = {s.id: s for s in sources}
    groups: dict[tuple[str, str], dict[str, list[Fact]]] = {}
    for f in require_sources(facts, sources):
        groups.setdefault((f.subject, f.key), {}).setdefault(_norm(f), []).append(f)

    out: list[Fact] = []
    for versions in groups.values():
        merged = []
        for same in versions.values():
            ids = list(dict.fromkeys(i for f in same for i in f.source_ids))
            merged.append((same[0], ids))
        conflicting = len(merged) > 1
        built = []
        for first, ids in merged:
            probe = first.model_copy(update={"source_ids": ids})
            dated = _dates(probe, by_id)
            newest = max(dated) if dated else None
            publishers = {by_id[i].publisher.lower() for i in ids}
            if conflicting:
                status = "conflicting"
            else:
                status = "confirmed" if len(publishers) >= 2 else "single-source"
            if newest is None:
                stale = True  # only undated sources
            elif first.key in STALE_KEYS:
                stale = today - newest > STALE_AFTER
            elif first.key.startswith("recent_news"):
                stale = today - newest > NEWS_STALE_AFTER
            else:
                stale = False
            built.append((newest, probe.model_copy(update={"status": status, "stale": stale})))
        # Most recent source first; undated sources lose ties.
        built.sort(key=lambda b: (b[0] is not None, b[0] or date.min), reverse=True)
        out.extend(f for _, f in built)
    return out

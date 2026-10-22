"""Convert the internal Briefing to the frontend `briefSchema` shape
(apps/web/src/lib/model.ts)."""

from __future__ import annotations

from datetime import timezone
from typing import Any

from .models import Briefing


def _fact_text(f) -> str:
    text = f.text
    if f.status == "single-source":
        text += " (unconfirmed: single source)"
    if f.status == "conflicting":
        text += " (conflicting sources)"
    if f.stale:
        text += " (may be out of date)"
    return text


def _uncertainty(b: Briefing) -> list[str]:
    out = list(b.missing)
    if b.identity_match == "likely":
        out.append("This is a likely match for the right person but not fully confirmed. Verify on the call.")
    seen: set[str] = set()
    for f in b.facts:
        if f.status == "conflicting":
            msg = f"Sources disagree on: {f.label.lower()}. Confirm directly."
        elif f.stale:
            msg = f"May be out of date: {f.label.lower()}."
        else:
            continue
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


def to_frontend_brief(b: Briefing) -> dict[str, Any]:
    labels = {f.id: f.label for f in b.facts}
    return {
        # Frontend only accepts the literal "demo" today. Live mode needs a
        # frontend schema change agreed with Aanand.
        "mode": "demo",
        "preparedAt": b.generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": b.summary,
        "facts": [{"label": f.label, "text": _fact_text(f), "sourceIds": list(f.source_ids)} for f in b.facts],
        "sources": [
            {"id": s.id, "title": s.title, "publisher": s.publisher, "excerpt": s.excerpt, "url": s.url}
            for s in b.sources
        ],
        "questions": [
            {"text": t.text, "basis": ", ".join(labels[i] for i in t.fact_ids if i in labels)}
            for t in b.talking_points
        ],
        "roleContext": b.role_context,
        "uncertainty": _uncertainty(b),
    }


def research_status(b: Briefing) -> str:
    """'partial' if there is any uncertainty, mirroring the frontend reducer."""
    return "partial" if _uncertainty(b) else "ready"

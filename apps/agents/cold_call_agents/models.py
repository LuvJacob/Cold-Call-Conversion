"""Internal data models for the research agents."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

ResearchStatus = Literal["not-started", "running", "ready", "partial", "failed"]
# "not-run" means person research did not finish (timeout/error), which is
# different from "unsure" (research ran but could not confirm the person).
IdentityMatch = Literal["confirmed", "likely", "unsure", "not-run"]
FactStatus = Literal["confirmed", "single-source", "conflicting"]


def clean_url(url: Any) -> Optional[str]:
    """Return url only if it is a well-formed http/https URL, else None."""
    if not isinstance(url, str) or re.search(r"\s", url):
        return None
    try:
        parts = urlparse(url)
        ok = parts.scheme.lower() in ("http", "https") and bool(parts.netloc) and bool(parts.hostname)
    except ValueError:
        return None
    return url if ok else None


class Prospect(BaseModel):
    prospect_id: str
    name: str
    company: str
    role: str
    company_domain: Optional[str] = None
    notes: str = ""
    seller_offering: Optional[str] = None
    revision: int = 0


class Source(BaseModel):
    id: str
    title: str
    publisher: str
    excerpt: str
    url: Optional[str] = None  # http/https only, or None
    date: Optional[str] = None  # ISO date (YYYY-MM-DD) or None

    @field_validator("url", mode="before")
    @classmethod
    def _http_only(cls, v: Any) -> Optional[str]:
        """Malformed or non-http(s) urls become None."""
        return clean_url(v)

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            date.fromisoformat(v)
        return v


class Fact(BaseModel):
    id: str
    subject: Literal["person", "company"]
    # Normalized field name, e.g. "current_role", "employee_count". Facts with
    # the same (subject, key) but different values are flagged as conflicting.
    # Multi-valued fields (news items) use a distinct key per item,
    # e.g. "recent_news.carrier_agreement".
    key: str
    label: str
    text: str
    value: str = ""  # comparable value; falls back to text when empty
    source_ids: list[str] = Field(default_factory=list)
    status: FactStatus = "single-source"
    stale: bool = False


class TalkingPoint(BaseModel):
    text: str
    fact_ids: list[str]


class Briefing(BaseModel):
    """Internal, richer briefing. The adapter converts it to the frontend shape."""

    prospect: Prospect
    identity_match: IdentityMatch
    summary: str
    role_context: str
    facts: list[Fact]
    sources: list[Source]
    talking_points: list[TalkingPoint]
    missing: list[str]
    generated_at: datetime
    mode: Literal["sample", "live"]

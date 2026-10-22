"""Person and company researchers.

v0 extraction is deterministic: facts come from profile records and from the
pre-extracted `claims` on search results. No LLM is used here yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from .guardrails import sanitize_web_text
from .models import Fact, IdentityMatch, Prospect, Source, clean_url
from .providers import LLMClient, ProfileClient, SearchClient, SearchResult

MAX_RESULTS = 5
_SUFFIX = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company|plc|gmbh)\b\.?", re.I)


@dataclass
class Budget:
    max_searches: int = 6
    timeout_seconds: float = 60
    max_profile_lookups: int = 2


def normalize_company(name: str) -> str:
    """Lowercase, drop punctuation and suffixes like Inc/LLC."""
    name = _SUFFIX.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.lower())


def _company_tokens(text: str) -> list[str]:
    return _tokens(normalize_company(text))


def _contains(hay: list[str], needle: list[str]) -> bool:
    """True if `needle` appears as a whole-token run in `hay` (never for empty)."""
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _mentions(result: SearchResult, prospect: Prospect) -> bool:
    """Result mentions both the person and the company as whole tokens."""
    return _contains(_tokens(result.content), _tokens(prospect.name)) and _contains(
        _company_tokens(result.content), _company_tokens(prospect.company)
    )


def extract_claims(result: SearchResult, llm: Optional[LLMClient]) -> list[dict[str, str]]:
    """Return structured claims for a search result.

    v0: fixtures ship pre-extracted claims. TODO: when a result has none, ask
    `llm` to extract claims from the sanitized content (inside a <data> block)
    so real Tavily results plug in without changing call sites.
    """
    return result.claims or []


def _clean_date(value: Optional[str]) -> Optional[str]:
    try:
        return date.fromisoformat(value).isoformat() if value else None
    except (ValueError, TypeError):
        return None


def _slug(key: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", sanitize_web_text(key, 80).lower()).strip("_")


class _Collector:
    """Builds sources (deduplicated) and facts with unique ids."""

    def __init__(self, prefix: str, llm: Optional[LLMClient]) -> None:
        self.prefix = prefix
        self.llm = llm
        self.sources: list[Source] = []
        self.facts: list[Fact] = []
        self._by_key: dict[Any, str] = {}

    def source(self, title: str, publisher: str, content: str, url: Optional[str], day: Optional[str]) -> str:
        url = clean_url(url)
        title = sanitize_web_text(title or "", 200, redact=True) or "Untitled source"
        publisher = sanitize_web_text(publisher or "", 120, redact=True) or "Unknown publisher"
        key = url or (title.lower(), publisher.lower())
        if key not in self._by_key:
            sid = f"{self.prefix}s{len(self.sources) + 1}"
            self._by_key[key] = sid
            self.sources.append(
                Source(
                    id=sid,
                    title=title,
                    publisher=publisher,
                    excerpt=sanitize_web_text(content or "", 300, redact=True),
                    url=url,
                    date=_clean_date(day),
                )
            )
        return self._by_key[key]

    def fact(self, subject: str, key: str, label: str, text: str, value: str, source_id: str) -> bool:
        key, label = _slug(key), sanitize_web_text(label, 80)
        text, value = sanitize_web_text(text, 300), sanitize_web_text(value, 200)
        if not (key and label and text):
            return False
        self.facts.append(
            Fact(
                id=f"{self.prefix}f{len(self.facts) + 1}",
                subject=subject,  # type: ignore[arg-type]
                key=key,
                label=label,
                text=text,
                value=value,
                source_ids=[source_id],
            )
        )
        return True

    def profile_source(self, profile: dict[str, Any], content: str) -> str:
        s = profile.get("source") or {}
        return self.source(
            s.get("title", "Profile record"), s.get("publisher", "Profile provider"),
            content, s.get("url"), s.get("date"),
        )

    def claims(self, results: list[SearchResult], subject: str) -> None:
        for r in results:
            sid = None
            for c in extract_claims(r, self.llm):
                if c.get("subject") != subject or not all(c.get(k) for k in ("key", "label", "text")):
                    continue
                sid = sid or self.source(r.title, r.publisher, r.content, r.url, r.published_date)
                self.fact(subject, c["key"], c["label"], c["text"], c.get("value", ""), sid)


def _safe_call(missing: list[str], what: str, fn, *args):
    """Run one provider call; on failure note it in `missing` and return None."""
    try:
        return fn(*args)
    except Exception as exc:
        missing.append(f"{what} failed ({type(exc).__name__}).")
        return None


def research_person(
    prospect: Prospect,
    search: SearchClient,
    profiles: ProfileClient,
    budget: Budget,
    llm: Optional[LLMClient] = None,
) -> tuple[IdentityMatch, list[Fact], list[Source], list[str]]:
    """Check identity first; collect person facts only if the match is not 'unsure'."""
    col = _Collector("p", llm)
    missing: list[str] = []

    profile = None
    if budget.max_profile_lookups > 0:
        profile = _safe_call(missing, "Person profile lookup", profiles.person, prospect.name, prospect.company)
    else:
        missing.append("Person profile lookup skipped (lookup budget reached).")
    company_toks = _company_tokens(prospect.company)
    profile_ok = bool(
        profile
        and company_toks
        and _tokens(str(profile.get("name", ""))) == _tokens(prospect.name)
        and _company_tokens(str(profile.get("company", ""))) == company_toks
    )

    results: list[SearchResult] = []
    if budget.max_searches > 0:
        query = f"{prospect.name} {prospect.company} talks articles"
        results = _safe_call(missing, "Public talks and articles search", search.search, query, MAX_RESULTS) or []
    else:
        missing.append("Public talks and articles were not searched (search budget reached).")

    mentions = [r for r in results if _mentions(r, prospect)]
    if profile_ok:
        identity: IdentityMatch = "confirmed"
    elif mentions:
        identity = "likely"
    else:
        return "unsure", [], [], missing

    if identity == "confirmed":
        title = sanitize_web_text(str(profile.get("title") or ""), 160)
        pname = sanitize_web_text(str(profile.get("name", "")), 120)
        sid = col.profile_source(profile, f"{pname}, {title} at {prospect.company}." if title else f"{pname} at {prospect.company}.")
        if title:
            col.fact("person", "current_role", "Current role", f"{title} at {prospect.company}.", title, sid)
        start = sanitize_web_text(str(profile.get("start_date") or ""), 60)
        if start:
            col.fact("person", "tenure", "In role since", f"In current role since {start}.", start, sid)
    col.claims(mentions, "person")

    if not any(f.key == "current_role" for f in col.facts):
        missing.append("Current role could not be found.")
    return identity, col.facts, col.sources, missing


def research_company(
    prospect: Prospect,
    search: SearchClient,
    profiles: ProfileClient,
    budget: Budget,
    llm: Optional[LLMClient] = None,
) -> tuple[list[Fact], list[Source], list[str]]:
    """Collect company facts and recent news."""
    col = _Collector("c", llm)
    missing: list[str] = []

    profile = None
    if budget.max_profile_lookups > 0:
        profile = _safe_call(missing, "Company profile lookup", profiles.company, prospect.company, prospect.company_domain)
    else:
        missing.append("Company profile lookup skipped (lookup budget reached).")
    if profile:
        industry = sanitize_web_text(str(profile.get("industry") or ""), 100)
        size = sanitize_web_text(str(profile.get("employee_count") or ""), 40)
        sid = col.profile_source(profile, f"{prospect.company}: {industry}." if industry else f"{prospect.company}.")
        if industry:
            col.fact("company", "industry", "Industry", f"Industry: {industry}.", industry, sid)
        if size:
            col.fact("company", "employee_count", "Company size", f"About {size} employees.", size, sid)

    for i, topic in enumerate(("about", "news")):
        if i >= budget.max_searches:
            missing.append(f"Company {topic} search skipped (search budget reached).")
            continue
        found = _safe_call(missing, f"Company {topic} search", search.search, f"{prospect.company} {topic}", MAX_RESULTS)
        col.claims(found or [], "company")

    if not any(f.key == "employee_count" for f in col.facts):
        missing.append("Company size could not be found.")
    if not any(f.key.startswith("recent_news") for f in col.facts):
        missing.append("No recent company news found.")
    return col.facts, col.sources, missing

"""Composite provider: free sources behind the existing SearchClient/ProfileClient Protocols.

One FreeSources instance serves one prospect. The researchers call
`profiles.company`, `search.search("<company> about")`, `search.search("<company> news")`
and `profiles.person`; we answer from Wikidata/Wikipedia, SEC EDGAR and the company
homepage, building the company bundle once and caching it. Each source fails on its
own: a timeout in one adds a note and the others still contribute.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import date
from typing import Any, Mapping, Optional

from ..guardrails import sanitize_web_text
from ..models import Prospect
from ..providers import SearchResult
from ..researchers import Budget
from .edgar import EdgarSource, edgar_user_agent
from .homepage import HomepageSource, default_resolver
from .http import HttpClient, HttpError, user_agent_from_env
from .wikidata import CompanyInfo, WikidataSource, domains_match

log = logging.getLogger("cold_call_agents.free_sources")


class TemplateLLM:
    """No-LLM writer stand-in: deterministic text built only from sanitized fields.
    (Unlike MockLLM it does not say "SAMPLE", since the facts are real.)"""

    def complete(self, system: str, prompt: str) -> str:
        field = lambda n: (m.group(1).strip() if (m := re.search(rf"^{n}: (.*)$", prompt, re.M)) else "")
        if "TASK: summary" in prompt:
            return (
                f"Call prep for {field('NAME')} ({field('ROLE')}) at {field('COMPANY')}, "
                f"built from {field('FACT_COUNT')} facts from free public sources."
            )
        if "TASK: talking_point" in prompt:
            return f"Reference this public fact: {field('TEXT')}"
        return ""


class FreeSources:
    """Implements SearchClient and ProfileClient."""

    def __init__(
        self,
        company: str,
        domain: Optional[str],
        http: HttpClient,
        *,
        sec_user_agent: Optional[str] = None,
        resolver=default_resolver,
        today: Optional[date] = None,
    ) -> None:
        self.company_name, self.domain, self.http = company, domain, http
        self._wd = WikidataSource(http)
        self._edgar = EdgarSource(http, sec_user_agent, today) if sec_user_agent else None
        self._home = HomepageSource(http, resolver, today)
        self._notes: dict[str, list[str]] = {"company": [], "person": []}
        self._lock = threading.Lock()
        self._bundle: Optional[tuple[Optional[CompanyInfo], list[SearchResult]]] = None

    def close(self) -> None:
        self.http.close()

    # -- notes (read by the researchers, optional hook) -------------------
    def notes(self, subject: str) -> list[str]:
        return list(dict.fromkeys(self._notes.get(subject, [])))

    def _note(self, subject: str, text: str) -> None:
        self._notes[subject].append(text)

    # -- company bundle ------------------------------------------------------
    def _company(self) -> tuple[Optional[CompanyInfo], list[SearchResult]]:
        with self._lock:
            if self._bundle is None:
                self._bundle = self._build_company()
            return self._bundle

    def _build_company(self) -> tuple[Optional[CompanyInfo], list[SearchResult]]:
        """Never raises: each source fails on its own with a note. Runs once (the result is cached)."""
        results: list[SearchResult] = []
        info: Optional[CompanyInfo] = None
        try:
            info, notes = self._wd.find_company(self.company_name, self.domain)
            for n in notes:
                self._note("company", n)
            if info:
                results += info.results
        except Exception as exc:
            info = None
            self._note("company", f"Wikidata/Wikipedia lookup failed ({_why(exc)}).")

        edgar_name_only = False
        if self._edgar:
            try:
                found, notes = self._edgar.lookup(self.company_name, info.cik if info else None)
                results += found
                for n in notes:
                    self._note("company", n)
                m = self._edgar.match
                edgar_name_only = bool(found) and not (info and info.cik)
                if edgar_name_only:
                    self._note("company", f"SEC filings matched to {_clean(m['title'])} (CIK {_clean(m['cik'])}) by exact name only; confirm it's the same company.")
            except Exception as exc:
                self._note("company", f"SEC EDGAR lookup failed ({_why(exc)}).")

        # A Wikidata match by name alone needs a second signal: the prospect's domain matching the
        # entity's website, or its SEC CIK agreeing with the exact-name EDGAR match.
        corroborated = False
        if info:
            by_domain = bool(self.domain and info.website and domains_match(info.website, self.domain))
            by_cik = bool(info.cik and self._edgar and self._edgar.match.get("name_cik") == int(info.cik))
            corroborated = by_domain or by_cik
            if not corroborated:
                self._note(
                    "company",
                    f"Company facts matched to {_clean(info.label)} (Wikidata {_clean(info.qid)}) by exact name only; confirm it's the same company.",
                )

        # Fetch only the prospect's own domain; fall back to the site Wikidata lists for the matched company.
        site = self.domain or (info.website if info else None)
        if site:
            unconfirmed = not self.domain and not corroborated
            try:
                found, notes = self._home.describe(_host_of(site), unconfirmed_site=unconfirmed)
            except Exception as exc:  # never let one source break the briefing
                found, notes = [], [f"Company website lookup failed ({_why(exc)})."]
            results += found
            for n in notes:
                self._note("company", n)
            if found and unconfirmed:
                self._note("company", "Company website was found through the Wikidata match (exact name only); confirm it's the same company.")
        else:
            self._note("company", "No company domain known, so the company website was not read.")
        return info, results

    # -- ProfileClient ------------------------------------------------------
    def company_profile(self) -> Optional[dict[str, Any]]:
        info, _ = self._company()
        return info.profile if info and info.profile.get("industry") else None

    def company(self, name: str, domain: Optional[str]) -> Optional[dict[str, Any]]:
        return self.company_profile()

    def person(self, name: str, company: str) -> Optional[dict[str, Any]]:
        try:
            profile = self._wd.person(name, company)
        except Exception as exc:
            self._note("person", f"Person lookup in Wikidata failed ({_why(exc)}).")
            return None
        if profile is None:
            self._note(
                "person",
                "No strong public identity match (name and current employer) in free sources, so person facts were left empty.",
            )
        return profile

    # -- SearchClient ---------------------------------------------------------
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        q = " ".join(query.lower().split())
        name = " ".join(self.company_name.lower().split())
        if q not in (f"{name} about", f"{name} news"):
            return []  # person queries: free sources do not cover non-notable people
        _, results = self._company()
        news = q.endswith(" news")
        picked = [
            r for r in results
            if any(c["key"].startswith("recent_news") for c in r.claims) == news
        ]
        return picked[:max_results]


def _clean(value: object) -> str:
    """Remote strings (labels, titles, header values) are data: sanitize and shorten before they reach a note."""
    return sanitize_web_text(str(value), 80, redact=True)


def _why(exc: Exception) -> str:
    return _clean(exc) if isinstance(exc, HttpError) else type(exc).__name__


def _host_of(site: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(site if "//" in site else f"//{site}").hostname or "").lower()


def build_free_providers(
    prospect: Prospect,
    budget: Budget = Budget(),
    env: Optional[Mapping[str, str]] = None,
    *,
    http: Optional[HttpClient] = None,
    resolver=default_resolver,
    today: Optional[date] = None,
) -> tuple[TemplateLLM, FreeSources, FreeSources]:
    """(llm, search, profiles) for one prospect. Reads SEC_USER_AGENT and RESEARCH_CONTACT."""
    env = os.environ if env is None else env
    http = http or HttpClient(
        max_requests=max(8, budget.max_searches * 4),
        deadline_seconds=budget.timeout_seconds,
        user_agent=user_agent_from_env(env),
    )
    sources = FreeSources(
        prospect.company, prospect.company_domain, http,
        sec_user_agent=edgar_user_agent(dict(env)), resolver=resolver, today=today,
    )
    return TemplateLLM(), sources, sources

"""Swappable provider interfaces plus SAMPLE-data mocks.

Real providers plug in here later by implementing the same Protocols:
  - LLMClient: IBM watsonx.ai or Gemini (undecided).
  - SearchClient: Tavily.
  - ProfileClient: People Data Labs.
Nothing in v0 makes a network call or reads an API key.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Optional, Protocol

FIXTURE_KEYS = ("northwind", "harborview", "cedarridge")


@dataclass
class SearchResult:
    title: str
    url: Optional[str]
    content: str
    published_date: Optional[str]
    publisher: str
    # v0 stand-in for LLM extraction: pre-extracted claims shipped with the
    # fixture. Real search providers leave this empty.
    claims: list[dict[str, str]] = field(default_factory=list)


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class SearchClient(Protocol):
    def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class ProfileClient(Protocol):
    def person(self, name: str, company: str) -> Optional[dict[str, Any]]: ...

    def company(self, name: str, domain: Optional[str]) -> Optional[dict[str, Any]]: ...


class _Counted:
    """Thread-safe call counter so tests can assert budget limits."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def _count(self) -> None:
        with self._lock:
            self.calls += 1


class MockLLM(_Counted):
    """Deterministic canned text. Never follows instructions found in prompts."""

    def complete(self, system: str, prompt: str) -> str:
        self._count()

        def field_of(name: str) -> str:
            m = re.search(rf"^{name}: (.*)$", prompt, re.M)
            return m.group(1).strip() if m else ""

        if "TASK: summary" in prompt:
            return (
                f"SAMPLE briefing for {field_of('NAME')} ({field_of('ROLE')}) at "
                f"{field_of('COMPANY')}, built from {field_of('FACT_COUNT')} sourced facts."
            )
        if "TASK: talking_point" in prompt:
            return f"Ask about their {field_of('LABEL').lower()}: {field_of('TEXT')}"
        return "SAMPLE response"


class MockSearch(_Counted):
    """Serves fixture search results. A result matches when any of its
    `keywords` appears in the query."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        super().__init__()
        self._results = results

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self._count()
        q = query.lower()
        hits = [r for r in self._results if any(k in q for k in r.get("keywords", []))]
        return [
            SearchResult(
                title=r["title"],
                url=r.get("url"),
                content=r["content"],
                published_date=r.get("published_date"),
                publisher=r["publisher"],
                claims=list(r.get("claims", [])),
            )
            for r in hits[:max_results]
        ]


class MockProfiles(_Counted):
    """Serves fixture profile records. Person lookup matches by name only,
    like a real lookup, so the researcher must check the company itself."""

    def __init__(self, person: Optional[dict[str, Any]], company: Optional[dict[str, Any]]) -> None:
        super().__init__()
        self._person = person
        self._company = company

    def person(self, name: str, company: str) -> Optional[dict[str, Any]]:
        self._count()
        p = self._person
        same = lambda a, b: " ".join(a.lower().split()) == " ".join(b.lower().split())
        return p if p and same(p["name"], name) else None

    def company(self, name: str, domain: Optional[str]) -> Optional[dict[str, Any]]:
        self._count()
        c = self._company
        if not c:
            return None
        if domain and c.get("domain", "").lower() == domain.lower():
            return c
        return c if c["name"].lower() == name.lower() else None


def load_fixture(key: str) -> dict[str, Any]:
    if key not in FIXTURE_KEYS:
        raise KeyError(f"unknown sample '{key}'; choose from {', '.join(FIXTURE_KEYS)}")
    text = (resources.files("cold_call_agents") / "fixtures" / f"{key}.json").read_text("utf-8")
    data = json.loads(text)
    assert data.get("sample") is True
    return data


def mocks_from_fixture(fx: dict[str, Any]) -> tuple[MockLLM, MockSearch, MockProfiles]:
    profiles = fx.get("profiles", {})
    return (
        MockLLM(),
        MockSearch(fx.get("search_results", [])),
        MockProfiles(profiles.get("person"), profiles.get("company")),
    )

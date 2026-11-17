"""Tavily web search as a SearchClient.

API relied on (docs: https://docs.tavily.com/documentation/api-reference/endpoint/search):
  POST https://api.tavily.com/search
  Headers: Authorization: Bearer <TAVILY_API_KEY>, Content-Type: application/json
  Body: {"query": str, "search_depth": "basic"|"advanced"|"fast"|"ultra-fast" (basic = 1 credit),
         "max_results": 0-20, "topic": "general"|"news"|"finance",
         "include_published_date": bool, "include_answer": false}
  200: {"query", "results": [{"title", "url", "content", "score", "published_date"|null}],
        "response_time", "request_id", ...}
  Errors: 400 invalid, 401 bad key, 422 validation, 429 rate limit (Retry-After),
          432/433 plan or pay-as-you-go limit, 500.
All body fields we send are documented there (verified against the current docs): `query`,
`search_depth`, `max_results`, `topic`, `include_published_date`, `include_answer`.
`published_date` is returned when `include_published_date` is true (beta; Tavily's best estimate
of publish or last-update time) and is enabled automatically for topic "news", so it is not
news-only; we send it explicitly for every query and use topic "news" only for "<company> news".
Result URLs are kept only when http/https (the frontend may render them as links).
We never request `answer` or `raw_content`. Results are untrusted web text: titles
and excerpts are sanitized (HTML, control chars, instruction-like sentences,
private data) before they leave this module. Failures become notes, not exceptions.
No `claims` are produced (extraction is the researchers' job, see providers.SearchResult).
"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx

from ..free_sources.http import HttpError
from ..guardrails import sanitize_web_text
from ..models import clean_url
from ..providers import SearchResult
from .dates import parse_date
from .http import LiveHttp, status_note

TAVILY_URL = "https://api.tavily.com/search"
NAME = "Tavily"


def _domain(url: Optional[str]) -> str:
    host = (urlsplit(url).hostname or "") if url else ""
    return host[4:] if host.startswith("www.") else host


class TavilySearch:
    """Implements SearchClient. One instance serves one prospect (budget is per instance)."""

    def __init__(
        self,
        api_key: str,
        http: LiveHttp,
        *,
        max_searches: int = 6,
        search_depth: str = "basic",
    ) -> None:
        self._key = api_key
        self.http = http
        self.max_searches = max_searches
        self.search_depth = search_depth
        self.searches = 0
        self._notes: list[str] = []
        self._lock = threading.Lock()

    def close(self) -> None:
        self.http.close()

    def notes(self, subject: str) -> list[str]:
        return list(dict.fromkeys(self._notes))

    def add_note(self, text: str) -> None:
        self._notes.append(text)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        with self._lock:
            if self.searches >= self.max_searches:
                self._notes.append("Tavily search skipped (search budget reached).")
                return []
            self.searches += 1
        body = {
            "query": query,
            "search_depth": self.search_depth,
            "max_results": max(1, min(int(max_results), 20)),
            "topic": "news" if query.rstrip().lower().endswith(" news") else "general",
            "include_published_date": True,
            "include_answer": False,
        }
        try:
            resp = self.http.post(
                TAVILY_URL, json=body,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            )
        except HttpError as exc:
            self._notes.append(f"Tavily search failed ({exc}).")
            return []
        if resp.status != 200:
            self._notes.append(status_note(NAME, resp.status))
            return []
        try:
            data = resp.json()
            items = data["results"]
            if not isinstance(items, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            self._notes.append("Tavily returned an unexpected response; results skipped.")
            return []
        out: list[SearchResult] = []
        for item in items:
            r = self._map(item)
            if r:
                out.append(r)
        return out[:max_results]

    @staticmethod
    def _map(item: Any) -> Optional[SearchResult]:
        if not isinstance(item, Mapping):
            return None
        url = clean_url(item.get("url"))
        content = sanitize_web_text(str(item.get("content") or ""), 2000, redact=True)
        title = sanitize_web_text(str(item.get("title") or ""), 200, redact=True)
        if not (content or title):
            return None
        return SearchResult(
            title=title or "Untitled source",
            url=url,
            content=content,
            published_date=parse_date(item.get("published_date")),
            publisher=sanitize_web_text(_domain(url), 120) or "Unknown publisher",
        )


def build_tavily(api_key: str, max_searches: int, deadline: float, *, transport: Optional[httpx.BaseTransport] = None, **kw: Any) -> TavilySearch:
    http = LiveHttp(
        max_requests=max_searches * 2 + 2, deadline_seconds=deadline, timeout=15.0,
        max_retries=1, transport=transport, **kw,
    )
    return TavilySearch(api_key, http, max_searches=max_searches)

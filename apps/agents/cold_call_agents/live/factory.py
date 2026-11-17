"""build_live_providers: (llm, search, profiles) for one prospect, mirroring build_free_providers.

Env: LLM_PROVIDER=watsonx|gemini (default watsonx), TAVILY_API_KEY, PDL_API_KEY,
WATSONX_API_KEY / WATSONX_URL / WATSONX_PROJECT_ID / WATSONX_MODEL_ID / WATSONX_API_VERSION,
GEMINI_API_KEY / GEMINI_MODEL, PDL_MIN_LIKELIHOOD (default 6).
Any provider whose key (or required setting) is missing falls back to the free sources, with a
note surfaced through the `notes(subject)` hook, so partial key setups still work.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Mapping, Optional

import httpx

from ..free_sources import TemplateLLM, build_free_providers
from ..models import Prospect
from ..researchers import Budget
from .gemini import DEFAULT_MODEL, build_gemini
from .pdl import DEFAULT_MIN_LIKELIHOOD, build_pdl
from .tavily import build_tavily
from .watsonx import DEFAULT_API_VERSION, DEFAULT_MODEL_ID, build_watsonx

log = logging.getLogger("cold_call_agents.live")


class _FreeFallback:
    """Wraps the free-sources object for one role and prefixes its notes with why we fell back."""

    def __init__(self, inner: Any, note: str) -> None:
        self._inner = inner
        self._extra = [note]

    def search(self, query: str, max_results: int):
        return self._inner.search(query, max_results)

    def person(self, name: str, company: str):
        return self._inner.person(name, company)

    def company(self, name: str, domain: Optional[str]):
        return self._inner.company(name, domain)

    def notes(self, subject: str) -> list[str]:
        return list(dict.fromkeys([*self._extra, *self._inner.notes(subject)]))

    def add_note(self, text: str) -> None:
        self._extra.append(text)

    def close(self) -> None:
        self._inner.close()


def _val(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _min_likelihood(env: Mapping[str, str]) -> int:
    try:
        n = int(_val(env, "PDL_MIN_LIKELIHOOD"))
        return n if 1 <= n <= 10 else DEFAULT_MIN_LIKELIHOOD
    except ValueError:
        return DEFAULT_MIN_LIKELIHOOD


def build_live_providers(
    prospect: Prospect,
    budget: Budget = Budget(),
    env: Optional[Mapping[str, str]] = None,
    *,
    transport: Optional[httpx.BaseTransport] = None,
    free_providers: Optional[tuple[Any, Any, Any]] = None,
    today: Optional[date] = None,
    **http_kw: Any,
) -> tuple[Any, Any, Any]:
    """(llm, search, profiles). `transport`/`http_kw` (e.g. sleep=) let tests run offline."""
    env = os.environ if env is None else env
    free_cache: list[Any] = []

    def free() -> Any:
        if not free_cache:
            free_cache.append(free_providers or build_free_providers(prospect, budget, env))
        return free_cache[0][1]

    llm_notes: list[str] = []
    wanted = (_val(env, "LLM_PROVIDER") or "watsonx").lower()
    if wanted not in ("watsonx", "gemini"):
        llm_notes.append(f"Unknown LLM_PROVIDER '{wanted[:20]}'; using watsonx.")
        wanted = "watsonx"

    llm: Any = None
    if wanted == "watsonx":
        missing = [n for n in ("WATSONX_API_KEY", "WATSONX_URL", "WATSONX_PROJECT_ID") if not _val(env, n)]
        if missing:
            llm_notes.append(f"{', '.join(missing)} not set; using template text instead of watsonx.ai.")
        elif not _val(env, "WATSONX_URL").lower().startswith("https://"):
            llm_notes.append("WATSONX_URL must start with https://; using template text instead of watsonx.ai.")
        else:
            llm = build_watsonx(
                _val(env, "WATSONX_API_KEY"), _val(env, "WATSONX_URL"), _val(env, "WATSONX_PROJECT_ID"),
                budget.timeout_seconds, model_id=_val(env, "WATSONX_MODEL_ID") or DEFAULT_MODEL_ID,
                api_version=_val(env, "WATSONX_API_VERSION") or DEFAULT_API_VERSION, transport=transport, **http_kw,
            )
    else:
        if not _val(env, "GEMINI_API_KEY"):
            llm_notes.append("GEMINI_API_KEY not set; using template text instead of Gemini.")
        else:
            llm = build_gemini(
                _val(env, "GEMINI_API_KEY"), budget.timeout_seconds,
                model=_val(env, "GEMINI_MODEL") or DEFAULT_MODEL, transport=transport, **http_kw,
            )
    if llm is None:
        llm = TemplateLLM()
        for n in llm_notes:
            log.warning(n)

    if _val(env, "TAVILY_API_KEY"):
        search: Any = build_tavily(_val(env, "TAVILY_API_KEY"), budget.max_searches, budget.timeout_seconds, transport=transport, **http_kw)
    else:
        search = _FreeFallback(free(), "TAVILY_API_KEY not set; web search used free public sources only.")

    if _val(env, "PDL_API_KEY"):
        profiles: Any = build_pdl(
            _val(env, "PDL_API_KEY"), budget.timeout_seconds, min_likelihood=_min_likelihood(env),
            transport=transport, today=(lambda: today) if today else date.today, **http_kw,
        )
    else:
        profiles = _FreeFallback(free(), "PDL_API_KEY not set; profiles came from free public sources only.")

    for n in llm_notes:  # surface LLM fallback notes where the researchers can read them
        search.add_note(n)
    return llm, search, profiles

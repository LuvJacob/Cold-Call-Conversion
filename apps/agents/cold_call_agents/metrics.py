"""Cost and speed tracking for one research run.

`run_research_with_metrics` (orchestrator.py) fills a `RunMetrics`: wall time per
stage, number of search/profile/HTTP requests, LLM tokens and an estimated cost.
Template and mock LLMs have no usage counter, so they report 0 tokens (mocks still
report calls via `.calls`). `http_requests` counts every HTTP attempt of the free-source
and live (tavily, pdl, watsonx incl. IAM, gemini) clients, retries included. Limits: request, token and HTTP counts are per-run
deltas, so sharing one client across concurrent runs mixes their counts; the stage time
of a researcher that timed out and was abandoned may be missing.

PRICES BELOW ARE PLACEHOLDERS, not real quotes. Update them from the provider
price pages, or override without code changes: set CCC_PRICES to a JSON string
or a path to a JSON file, e.g.
  {"models": {"gemini-flash-lite-latest": [0.10, 0.40]}, "search_per_request": 0.008}
Model prices are [input, output] USD per 1M tokens.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Optional

log = logging.getLogger("cold_call_agents.metrics")

STAGES = ("person", "company", "guardrails", "verify", "write")

# PLACEHOLDER prices (USD per 1M tokens: input, output). Update before trusting cost numbers.
DEFAULT_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gemini-flash-lite-latest": (0.10, 0.40),  # PLACEHOLDER
    "ibm/granite-3-3-8b-instruct": (0.20, 0.20),  # PLACEHOLDER
}


def _price(value: Any) -> float:
    """A finite, non-negative number, else ValueError."""
    if isinstance(value, bool):
        raise ValueError("not a price")
    x = float(value)
    if not math.isfinite(x) or x < 0:
        raise ValueError("invalid price")
    return x


@dataclass
class PriceTable:
    models: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(DEFAULT_MODEL_PRICES))
    search_per_request: float = 0.0  # PLACEHOLDER: set to your search plan's cost per call
    profile_per_request: float = 0.0  # PLACEHOLDER: set to your profile plan's cost per lookup

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "PriceTable":
        """Defaults, overridden by CCC_PRICES (inline JSON or a JSON file path). Bad input is ignored."""
        env = os.environ if env is None else env
        raw = (env.get("CCC_PRICES") or "").strip()
        table = cls()
        if not raw:
            return table
        try:
            text = raw if raw.startswith("{") else Path(raw).read_text("utf-8")
            data = json.loads(text)
            models = dict(table.models)  # build into a copy; apply only if everything is valid
            for model, pair in (data.get("models") or {}).items():
                models[str(model)] = (_price(pair[0]), _price(pair[1]))
            search = _price(data.get("search_per_request", table.search_per_request))
            profile = _price(data.get("profile_per_request", table.profile_per_request))
        except (OSError, ValueError, TypeError, IndexError, AttributeError):
            log.warning("CCC_PRICES could not be used (unreadable or invalid); using default placeholder prices.")
            return cls()
        table.models, table.search_per_request, table.profile_per_request = models, search, profile
        return table

    def estimate(self, model: str, input_tokens: int, output_tokens: int, searches: int = 0, profiles: int = 0) -> float:
        p_in, p_out = self.models.get(model, (0.0, 0.0))
        return (
            input_tokens * p_in / 1e6
            + output_tokens * p_out / 1e6
            + searches * self.search_per_request
            + profiles * self.profile_per_request
        )


@dataclass
class RunMetrics:
    prospect_id: str = ""
    stage_seconds: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    search_requests: int = 0
    profile_requests: int = 0
    http_requests: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_model: str = ""
    est_cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage_seconds"] = {k: round(v, 4) for k, v in self.stage_seconds.items()}
        d["total_seconds"] = round(self.total_seconds, 4)
        d["est_cost_usd"] = round(self.est_cost_usd, 6)
        return d

    def log_line(self) -> str:
        """One structured line per run. Only the prospect id identifies the run (no name/company)."""
        return "research_run " + json.dumps(self.as_dict(), sort_keys=True)


class StageRecorder:
    """Thread-safe wall-time recorder (person and company research run in parallel)."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self._lock = threading.Lock()

    @contextmanager
    def stage(self, name: str):
        t0 = perf_counter()
        try:
            yield
        finally:
            with self._lock:
                self.seconds[name] = self.seconds.get(name, 0.0) + perf_counter() - t0

    def timed(self, name: str, fn, *args):
        with self.stage(name):
            return fn(*args)


class NullRecorder:
    """Default recorder: adds no timing and no overhead."""

    @contextmanager
    def stage(self, name: str):
        yield

    def timed(self, name: str, fn, *args):
        return fn(*args)


class CountingProxy:
    """Wraps a search or profile client and counts the calls made through it."""

    def __init__(self, inner: Any, methods: tuple[str, ...]) -> None:
        self._inner = inner
        self._methods = methods
        self.count = 0
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name in self._methods and callable(attr):

            def counted(*a, **kw):
                with self._lock:
                    self.count += 1
                return attr(*a, **kw)

            return counted
        return attr


def http_request_count(*providers: Any) -> int:
    """Best effort: sums `requests_made` from distinct HttpClients (free sources and the live
    tavily/pdl/watsonx/gemini clients expose `.http`; every attempt, retries and the IAM fetch
    included, is counted once in HttpClient._spend). Only counts are read, never URLs or headers."""
    seen: list[Any] = []
    for p in providers:
        inner = getattr(p, "_inner", p)
        client = getattr(inner, "http", None) or getattr(inner, "_http", None)
        if client is not None and not any(client is s for s in seen):
            seen.append(client)
    return sum(int(getattr(c, "requests_made", 0) or 0) for c in seen)


def llm_snapshot(llm: Any) -> tuple[int, int, int]:
    u = getattr(llm, "usage", None)
    if u is None:  # mock LLMs count calls on `.calls` and have no tokens
        calls = getattr(llm, "calls", 0)
        return (calls if isinstance(calls, int) else 0, 0, 0)
    return (int(getattr(u, "calls", 0)), int(getattr(u, "input_tokens", 0)), int(getattr(u, "output_tokens", 0)))


def llm_model_id(llm: Any) -> str:
    return str(getattr(llm, "model", None) or getattr(llm, "model_id", None) or type(llm).__name__)

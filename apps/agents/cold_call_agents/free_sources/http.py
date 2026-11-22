"""Shared HTTP helper for the free sources.

One place for: per-request timeout, a small retry with backoff on 429/5xx, a
descriptive User-Agent, a hard cap on response size, and an overall request
budget (count and wall-clock) so a briefing never makes unbounded calls.
Redirects are never followed here; callers that need them handle them.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

# Wikimedia policy wants a way to reach the operator; this is the public repo, not a person.
DEFAULT_USER_AGENT = "ColdCallConversion/0.1 (https://github.com/LuvJacob/Cold-Call-Conversion; research prototype)"
RETRY_STATUSES = (429, 500, 502, 503, 504)  # other 4xx are never retried
MAX_RETRY_WAIT = 5.0
# Minimum seconds between requests to a host (SEC allows 10/s; we stay far below).
_MIN_INTERVAL = {"www.sec.gov": 0.25, "data.sec.gov": 0.25, "www.wikidata.org": 0.15, "en.wikipedia.org": 0.15}


class HttpError(Exception):
    """Any failed fetch. The message is safe to show as a `missing` note."""


class BudgetExhausted(HttpError):
    pass


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        enc = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            enc = ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(enc, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body)


def user_agent_from_env(env: Optional[Mapping[str, str]] = None) -> str:
    """Generic project UA; contact info only if RESEARCH_CONTACT is set."""
    contact = ((env if env is not None else os.environ).get("RESEARCH_CONTACT") or "").strip()
    return f"{DEFAULT_USER_AGENT[:-1]}; {contact})" if contact else DEFAULT_USER_AGENT


class HttpClient:
    def __init__(
        self,
        *,
        max_requests: int = 24,
        deadline_seconds: Optional[float] = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        backoff: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.max_requests = max_requests
        self.requests_made = 0
        self._deadline = clock() + deadline_seconds if deadline_seconds else None
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        # No connection reuse (a TLS session verified for one host must never serve another,
        # which matters for IP-pinned requests) and no proxy/env configuration.
        self._client = httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    def close(self) -> None:
        self._client.close()

    def _spend(self, host: str) -> None:
        wait = 0.0
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise BudgetExhausted("request budget reached")
            self._check_deadline()
            self.requests_made += 1
            gap = _MIN_INTERVAL.get(host, 0.0)
            if gap:
                now = self._clock()
                start = max(now, self._last.get(host, 0.0) + gap)
                self._last[host] = start  # reserve our slot, then sleep outside the lock
                wait = start - now
        if wait > 0:
            self._sleep(wait)

    def _check_deadline(self) -> None:
        if self._deadline is not None and self._clock() > self._deadline:
            raise BudgetExhausted("time budget reached")

    def get(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        max_bytes: int = 2_000_000,
        content_types: Optional[tuple[str, ...]] = None,
        pin_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> HttpResponse:
        """GET with retry. Returns non-2xx responses to the caller (after
        retries on 429/5xx); raises HttpError on timeout, network error,
        oversize body or unwanted content type.

        `pin_ip` connects to that already-validated IP while keeping the real
        hostname for Host/SNI/certificate checks (prevents DNS rebinding).
        """
        parts = urlsplit(url)
        host = parts.hostname or ""
        hdrs = {"User-Agent": user_agent or self.user_agent}
        hdrs.update(headers or {})
        ext: dict[str, Any] = {}
        target = url
        if pin_ip:
            ip = f"[{pin_ip}]" if ":" in pin_ip else pin_ip
            port = f":{parts.port}" if parts.port else ""
            target = urlunsplit((parts.scheme, f"{ip}{port}", parts.path, parts.query, ""))
            hdrs["Host"] = parts.netloc
            ext["sni_hostname"] = host
        for attempt in range(self._max_retries + 1):
            self._spend(host)
            try:
                resp = self._once(target, params, hdrs, ext, max_bytes, content_types, url)
            except httpx.TimeoutException as exc:
                raise HttpError("timed out") from exc
            except httpx.HTTPError as exc:
                raise HttpError(f"network error ({type(exc).__name__})") from exc
            except (httpx.InvalidURL, ValueError) as exc:  # e.g. a hostile redirect Location
                raise HttpError("invalid URL in response") from exc
            if resp.status in RETRY_STATUSES and attempt < self._max_retries:
                ra = resp.headers.get("retry-after", "").strip()
                delay = float(ra) if ra.isdigit() else self._backoff * (2**attempt) + random.uniform(0, 0.25)
                self._sleep(min(delay, MAX_RETRY_WAIT))
                continue
            return resp
        raise HttpError("unreachable")  # pragma: no cover

    def _once(self, target, params, hdrs, ext, max_bytes, content_types, shown_url) -> HttpResponse:
        with self._client.stream("GET", target, params=params, headers=hdrs, extensions=ext) as r:
            headers = {k.lower(): v for k, v in r.headers.items()}
            if r.status_code == 200:
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                if content_types and ctype not in content_types:
                    raise HttpError(f"unsupported content type '{ctype or 'unknown'}'")
                if headers.get("content-length", "").isdigit() and int(headers["content-length"]) > max_bytes:
                    raise HttpError("response too large")
            body = bytearray()
            for chunk in r.iter_bytes():
                self._check_deadline()
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise HttpError("response too large")
            return HttpResponse(r.status_code, headers, bytes(body), shown_url)

    def get_json(self, url: str, **kw: Any) -> Any:
        resp = self.get(url, **kw)
        if resp.status != 200:
            raise HttpError(f"HTTP {resp.status}")
        try:
            return resp.json()
        except ValueError as exc:
            raise HttpError("invalid JSON") from exc

    def get_obj(self, url: str, **kw: Any) -> dict:
        """Like get_json but the top-level value must be a JSON object."""
        data = self.get_json(url, **kw)
        if not isinstance(data, dict):
            raise HttpError("unexpected JSON shape")
        return data

"""HTTP for the paid providers: the free-sources HttpClient plus POST.

Reuses its timeout, retry-with-backoff on 429/5xx, User-Agent, size cap and
request/time budget. The API hosts are fixed and trusted (no SSRF IP pinning).
Non-2xx responses are returned to the caller after retries; network errors,
timeouts and oversize bodies raise HttpError (safe to show as a note).
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..free_sources.http import RETRY_STATUSES, HttpClient, HttpError, HttpResponse

__all__ = ["HttpError", "HttpResponse", "LiveHttp", "status_note"]


class LiveHttp(HttpClient):
    def post(
        self,
        url: str,
        *,
        json: Any = None,
        data: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, str]] = None,
        max_bytes: int = 2_000_000,
    ) -> HttpResponse:
        host = httpx.URL(url).host
        hdrs = {"User-Agent": self.user_agent, **(headers or {})}
        for attempt in range(self._max_retries + 1):
            self._spend(host)
            try:
                resp = self._post_once(url, json, data, hdrs, params, max_bytes)
            except httpx.TimeoutException as exc:
                raise HttpError("timed out") from exc
            except httpx.HTTPError as exc:
                raise HttpError(f"network error ({type(exc).__name__})") from exc
            if resp.status in RETRY_STATUSES and attempt < self._max_retries:
                delay = self._backoff * (2**attempt)
                ra = resp.headers.get("retry-after", "")
                if ra.isdigit():
                    delay = float(ra)
                self._sleep(min(delay, 5.0))
                continue
            return resp
        raise HttpError("unreachable")  # pragma: no cover

    def _post_once(self, url, json, data, hdrs, params, max_bytes) -> HttpResponse:
        with self._client.stream("POST", url, json=json, data=data, headers=hdrs, params=params) as r:
            body = bytearray()
            for chunk in r.iter_bytes():
                self._check_deadline()
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise HttpError("response too large")
            return HttpResponse(r.status_code, {k.lower(): v for k, v in r.headers.items()}, bytes(body), url)


def status_note(provider: str, status: int) -> str:
    """Safe note for a failed call (never includes response bodies, which may echo input)."""
    if status in (401, 403):
        return f"{provider} rejected the API key (HTTP {status}); check it in the worker environment."
    if status in (402, 432, 433):
        return f"{provider} usage or payment limit reached (HTTP {status})."
    if status == 429:
        return f"{provider} rate limit reached (HTTP 429); results skipped."
    if status >= 500:
        return f"{provider} is unavailable (HTTP {status}); results skipped."
    return f"{provider} request failed (HTTP {status})."

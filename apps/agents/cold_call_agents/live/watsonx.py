"""IBM watsonx.ai as an LLMClient.

APIs relied on (docs: https://cloud.ibm.com/apidocs/watsonx-ai#text-chat,
https://cloud.ibm.com/docs/account?topic=account-iamtoken_from_apikey):
  1. IAM token: POST https://iam.cloud.ibm.com/identity/token
       Content-Type: application/x-www-form-urlencoded
       body: grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey=<WATSONX_API_KEY>
       200: {"access_token", "expires_in" (seconds, about 3600), "expiration" (epoch)}
     Cached and reused until 5 minutes before expiry; refreshed on a 401 from the model call.
  2. Chat: POST {WATSONX_URL}/ml/v1/text/chat?version=<WATSONX_API_VERSION>
       Authorization: Bearer <token>
       body: {"model_id", "project_id", "messages": [{"role": "system"|"user", "content"}],
              "max_completion_tokens", "temperature"}
       200: {"choices": [{"message": {"content"}}], "usage": {"prompt_tokens", "completion_tokens", ...}}
     (`max_tokens` is deprecated in favour of `max_completion_tokens`.)
Checked against https://cloud.ibm.com/apidocs/watsonx-ai#text-chat: the body field is
`max_completion_tokens` (confirmed; `max_tokens` is deprecated and ignored if both are sent),
and `model_id` plus `project_id` are body fields. That page lists no `version` query parameter
for POST /ml/v1/text/chat and no latest date, so the `version` we send (default 2024-05-31, a
date IBM has accepted historically) is unconfirmed; it is env-configurable (WATSONX_API_VERSION),
as is the model id (WATSONX_MODEL_ID).
Concurrent 401s trigger one IAM refresh, not one per thread (the stale token is compared).

complete() raises LLMError on any failure; writer.py already falls back to a template.
Token usage is added to `self.usage` after every successful call.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

import httpx

from ..free_sources.http import HttpError
from .http import LiveHttp
from .usage import LLMError, TokenUsage

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
GRANT = "urn:ibm:params:oauth:grant-type:apikey"
# Small IBM instruct model from watsonx.ai's supported list: cheap per token and enough for
# 2-4 sentence call-prep summaries. Override with WATSONX_MODEL_ID.
DEFAULT_MODEL_ID = "ibm/granite-3-3-8b-instruct"
DEFAULT_API_VERSION = "2024-05-31"
TOKEN_REFRESH_MARGIN = 300  # seconds before expiry to refresh


class WatsonxLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        project_id: str,
        http: LiveHttp,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        api_version: str = DEFAULT_API_VERSION,
        max_output_tokens: int = 400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._project = project_id
        self.http = http
        self.model_id = model_id
        self.api_version = api_version
        self.max_output_tokens = max_output_tokens
        self._clock = clock
        self._token: Optional[str] = None
        self._token_expires = 0.0
        self._lock = threading.Lock()
        self.usage = TokenUsage()

    def close(self) -> None:
        self.http.close()

    def _access_token(self, stale: Optional[str] = None) -> str:
        """Cached token; `stale` is a token that just got a 401. Refresh only if it is still the cached one."""
        with self._lock:
            force = stale is not None and self._token == stale
            if force or not self._token or self._clock() >= self._token_expires - TOKEN_REFRESH_MARGIN:
                self._token = None
                try:
                    resp = self.http.post(
                        IAM_URL, data={"grant_type": GRANT, "apikey": self._key},
                        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                    )
                except HttpError as exc:
                    raise LLMError(f"watsonx token request failed ({exc})") from exc
                if resp.status != 200:
                    raise LLMError(f"watsonx token request rejected (HTTP {resp.status})")
                try:
                    body = resp.json()
                    token, ttl = body["access_token"], float(body.get("expires_in") or 3600)
                except (ValueError, KeyError, TypeError) as exc:
                    raise LLMError("watsonx token response was unexpected") from exc
                self._token, self._token_expires = token, self._clock() + ttl
            return self._token  # type: ignore[return-value]

    def _chat(self, token: str, system: str, prompt: str):
        body: dict[str, Any] = {
            "model_id": self.model_id,
            "project_id": self._project,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_completion_tokens": self.max_output_tokens,
            "temperature": 0,
        }
        return self.http.post(
            f"{self._base}/ml/v1/text/chat", json=body, params={"version": self.api_version},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        )

    def complete(self, system: str, prompt: str) -> str:
        try:
            token = self._access_token()
            resp = self._chat(token, system, prompt)
            if resp.status == 401:  # token revoked or expired early: refresh once
                resp = self._chat(self._access_token(stale=token), system, prompt)
        except HttpError as exc:
            raise LLMError(f"watsonx call failed ({exc})") from exc
        if resp.status != 200:
            raise LLMError(f"watsonx call failed (HTTP {resp.status})")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("watsonx response was unexpected") from exc
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        self.usage.add(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return text if isinstance(text, str) else ""


def build_watsonx(
    api_key: str, base_url: str, project_id: str, deadline: float, *,
    model_id: str = DEFAULT_MODEL_ID, api_version: str = DEFAULT_API_VERSION,
    transport: Optional[httpx.BaseTransport] = None, clock: Callable[[], float] = time.time, **kw: Any,
) -> WatsonxLLM:
    http = LiveHttp(max_requests=24, deadline_seconds=deadline, timeout=30.0, max_retries=1, transport=transport, **kw)
    return WatsonxLLM(api_key, base_url, project_id, http, model_id=model_id, api_version=api_version, clock=clock)

"""Google Gemini as a fallback LLMClient.

API relied on (docs: https://aistudio.google.com/api-reference/generate-content):
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
  Header: x-goog-api-key: <GEMINI_API_KEY>
  body: {"systemInstruction": {"parts": [{"text"}]},
         "contents": [{"role": "user", "parts": [{"text"}]}],
         "generationConfig": {"maxOutputTokens", "temperature"}}
  200: {"candidates": [{"content": {"parts": [{"text"}]}, "finishReason"}],
        "usageMetadata": {"promptTokenCount", "candidatesTokenCount"}}
The default model is the `gemini-flash-lite-latest` alias (a cheap Flash-Lite model that tracks
the current release); pin one with GEMINI_MODEL. Model ids retire over time, so verify.
complete() raises LLMError on failure; token usage is added to `self.usage`.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..free_sources.http import HttpError
from .http import LiveHttp
from .usage import LLMError, TokenUsage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"


class GeminiLLM:
    def __init__(self, api_key: str, http: LiveHttp, *, model: str = DEFAULT_MODEL, max_output_tokens: int = 400) -> None:
        self._key = api_key
        self.http = http
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.usage = TokenUsage()

    def close(self) -> None:
        self.http.close()

    def complete(self, system: str, prompt: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": self.max_output_tokens, "temperature": 0},
        }
        try:
            resp = self.http.post(
                f"{BASE_URL}/{self.model}:generateContent", json=body,
                headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
            )
        except HttpError as exc:
            raise LLMError(f"gemini call failed ({exc})") from exc
        if resp.status != 200:
            raise LLMError(f"gemini call failed (HTTP {resp.status})")
        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError("gemini response was unexpected (possibly blocked)") from exc
        meta = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        self.usage.add(meta.get("promptTokenCount"), meta.get("candidatesTokenCount"))
        return text


def build_gemini(
    api_key: str, deadline: float, *, model: str = DEFAULT_MODEL,
    transport: Optional[httpx.BaseTransport] = None, **kw: Any,
) -> GeminiLLM:
    http = LiveHttp(max_requests=24, deadline_seconds=deadline, timeout=30.0, max_retries=1, transport=transport, **kw)
    return GeminiLLM(api_key, http, model=model)

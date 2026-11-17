"""Offline helpers for the live-provider tests. Sample data in tests/data/live is FICTIONAL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx

DATA = Path(__file__).parent / "data" / "live"


def raw(name: str) -> bytes:
    return (DATA / name).read_bytes()


def jresp(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=raw(name), headers={"content-type": "application/json"})


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


class Recorder:
    """MockTransport handler: records requests, answers with a function or a fixed response."""

    def __init__(self, answer: httpx.Response | Callable[[httpx.Request], httpx.Response]):
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, httpx.Response):
            r = self.answer  # fresh copy per call: a Response body can only be streamed once
            return httpx.Response(r.status_code, content=r.content, headers=r.headers)
        return self.answer(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def no_sleep(_s: float) -> None:
    return None

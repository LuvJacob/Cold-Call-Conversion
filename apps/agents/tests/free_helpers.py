"""Offline test helpers for the free sources: a fake network over httpx.MockTransport.

All fixture data in tests/data/free_sources is FICTIONAL ("Acme Robotics Sample Inc"),
hand-written in the shape of the real Wikidata / Wikipedia / SEC / HTML responses.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from cold_call_agents.free_sources.http import HttpClient

DATA = Path(__file__).parent / "data" / "free_sources"
TODAY = date(2026, 11, 17)
PUBLIC_IP = "93.184.216.34"
SITE = "www.acme-robotics.example"


def raw(name: str) -> bytes:
    return (DATA / name).read_bytes()


def jr(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=raw(name), headers={"content-type": "application/json"})


def html(name: str, status: int = 200, ctype: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(status, content=raw(name), headers={"content-type": ctype})


def resolver_ok(host: str) -> list[str]:
    return [PUBLIC_IP]


class FakeNet:
    """Routes requests by (host, path). `over` maps (host, path) to a Response or a callable.
    For pinned (IP) requests the real host comes from the Host header, as it would on the wire."""

    def __init__(self, search: str = "wd_search_acme.json", over: dict | None = None):
        self.search, self.over, self.calls, self.requests = search, over or {}, [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = (request.headers.get("host") or request.url.host).split(":")[0]
        path, q = request.url.path, dict(request.url.params)
        self.calls.append((host, path))
        self.requests.append(request)
        v = self.over.get((host, path))
        if v is not None:
            return v(request) if callable(v) else v
        if host == "www.wikidata.org":
            if q.get("action") == "wbsearchentities":
                return jr(self.search)
            ids = q.get("ids", "").split("|")
            src = "wd_labels.json" if q.get("props") == "labels" else "wd_entities.json"
            ents = json.loads(raw(src))["entities"]
            return httpx.Response(200, json={"entities": {i: ents[i] for i in ids if i in ents}})
        if host == "en.wikipedia.org":
            return jr("wp_summary_acme.json")
        if host == "www.sec.gov" and path == "/files/company_tickers.json":
            return jr("sec_tickers.json")
        if host == "data.sec.gov":
            return jr("sec_submissions.json")
        if host == SITE:
            if path == "/robots.txt":
                return httpx.Response(404, text="")
            if path == "/":
                return html("homepage.html")
            if path == "/about":
                return html("about.html")
        return httpx.Response(404, text="not found")

    def hosts(self) -> set[str]:
        return {h for h, _ in self.calls}


def make_http(net: FakeNet, **kw) -> HttpClient:
    kw.setdefault("sleep", lambda s: None)
    return HttpClient(transport=httpx.MockTransport(net), **kw)

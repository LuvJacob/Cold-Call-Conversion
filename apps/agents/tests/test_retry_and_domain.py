"""429/503 retry in the free-source HTTP client and domain disambiguation in Wikidata (offline)."""

from __future__ import annotations

import json

import httpx
import pytest
from free_helpers import make_http, raw
from test_free_sources_adversarial import wikidata_net

from cold_call_agents.free_sources.http import HttpClient, HttpError
from cold_call_agents.free_sources.wikidata import WikidataSource

URL = "https://www.example.com/x"


def client(statuses, headers=None):
    seq = list(statuses)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(seq.pop(0), json={"ok": True}, headers=headers or {})

    sleeps: list[float] = []
    http = HttpClient(transport=httpx.MockTransport(handler), sleep=sleeps.append, max_requests=10)
    return http, sleeps, calls


def test_429_then_200_succeeds_and_counts_requests():
    http, sleeps, _ = client([429, 200])
    assert http.get_json(URL) == {"ok": True}
    assert http.requests_made == 2 and len(sleeps) == 1 and 1.0 <= sleeps[0] <= 1.3


def test_retry_after_honored_and_capped():
    http, sleeps, _ = client([429, 200], {"retry-after": "3"})
    http.get_json(URL)
    assert sleeps == [3.0]
    http, sleeps, _ = client([503, 200], {"retry-after": "120"})
    http.get_json(URL)
    assert sleeps == [5.0]


def test_repeated_429_gives_same_failure_and_three_attempts():
    http, sleeps, calls = client([429, 429, 429])
    with pytest.raises(HttpError, match="HTTP 429"):
        http.get_json(URL)
    assert len(calls) == 3 and http.requests_made == 3 and len(sleeps) == 2
    assert 2.0 <= sleeps[1] <= 2.3


def test_404_not_retried():
    http, sleeps, calls = client([404, 200])
    with pytest.raises(HttpError, match="HTTP 404"):
        http.get_json(URL)
    assert len(calls) == 1 and not sleeps


def test_budget_still_applies_to_retries():
    http, _, calls = client([429, 429, 200])
    http.max_requests = 2
    with pytest.raises(HttpError):
        http.get_json(URL)
    assert len(calls) == 2


def test_domain_picks_the_right_candidate_among_several():
    ents = json.loads(raw("wd_entities.json"))["entities"]
    a, b = ents["Q900001"], ents["Q900002"]
    for e, site in ((a, "https://www.homedepot.com/"), (b, "https://other.example/")):
        e["labels"] = {"en": {"value": "Home Depot"}}
        e["aliases"] = {"en": []}
        e["claims"]["P856"] = [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"value": site}}}]
    a["labels"] = {"en": {"value": "The Home Depot"}}  # leading "The" is ignored when comparing

    def src():
        return WikidataSource(make_http(wikidata_net(ents, ["Q900002", "Q900001"])))

    info, _ = src().find_company("Home Depot", "homedepot.com")
    assert info and info.qid == "Q900001"
    info, _ = src().find_company("The Home Depot", "www.homedepot.com")
    assert info and info.qid == "Q900001"
    info, notes = src().find_company("Home Depot", "nomatch.example")  # first candidate is never picked
    assert info is None and notes
    info, notes = src().find_company("Home Depot", None)
    assert info is None and notes

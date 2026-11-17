import json
from datetime import date

import httpx
import pytest

from cold_call_agents.live.pdl import COMPANY_URL, PERSON_URL, build_pdl
from cold_call_agents.models import Prospect
from cold_call_agents.researchers import Budget, research_company, research_person
from live_helpers import Recorder, jresp, no_sleep, raw

TODAY = date(2026, 11, 17)
PRIVATE = ["jordan.private", "4155550199", "Private Lane", "1980", "1 Private Way", "birth", "phone", "email", "jordan@acme"]


def make(answer, **kw):
    rec = Recorder(answer)
    return build_pdl("pdl-TESTKEY", 60, transport=rec.transport, sleep=no_sleep, today=lambda: TODAY, **kw), rec


def test_person_request_and_mapping():
    p, rec = make(jresp("pdl_person.json"))
    out = p.person("Jordan Sample", "Acme Robotics Sample Inc")
    req = rec.requests[0]
    assert req.method == "GET" and str(req.url).startswith(PERSON_URL)
    assert req.headers["x-api-key"] == "pdl-TESTKEY"
    q = dict(req.url.params)
    assert q["name"] == "Jordan Sample" and q["company"] == "Acme Robotics Sample Inc"
    assert q["min_likelihood"] == "6" and "pdl-TESTKEY" not in str(req.url)
    assert out["name"] == "Jordan Sample" and out["title"] == "Vp Of Operations"
    assert out["company"] == "Acme Robotics Sample Inc"
    assert out["seniority"] == ["vp"] and out["start_date"] == "2021-03-01"
    assert out["past_employers"] == ["Globex Fictional Ltd", "Initech Sample"]
    assert out["source"]["publisher"] == "People Data Labs" and out["source"]["date"] == "2026-11-17"


def test_person_privacy_filter():
    p, _ = make(jresp("pdl_person.json"))
    dumped = json.dumps(p.person("Jordan Sample", "Acme")).lower()
    for bad in PRIVATE:
        assert bad.lower() not in dumped, bad


def test_company_request_and_mapping():
    p, rec = make(jresp("pdl_company.json"))
    out = p.company("Acme Robotics Sample Inc", "acme-robotics.example")
    req = rec.requests[0]
    assert str(req.url).startswith(COMPANY_URL) and req.headers["x-api-key"] == "pdl-TESTKEY"
    assert dict(req.url.params)["website"] == "acme-robotics.example"
    assert out["name"] == "Acme Robotics Sample Inc" and out["industry"] == "Machinery"
    assert out["employee_count"] == 420 and out["hq_city"] == "Austin" and out["founded"] == 2009
    assert out["website"] == "acme-robotics.example"
    assert "Private Way" not in json.dumps(out)


def test_company_size_range_when_no_count():
    body = json.loads(raw("pdl_company.json"))
    del body["employee_count"]
    p, _ = make(httpx.Response(200, json=body))
    assert p.company("Acme", None)["employee_count"] == "201-500"


def test_company_without_domain_omits_website_param():
    p, rec = make(jresp("pdl_company.json"))
    p.company("Acme", None)
    assert "website" not in dict(rec.requests[0].url.params)


def test_missing_fields_are_tolerated():
    p, _ = make(httpx.Response(200, json={"status": 200, "likelihood": 7, "data": {"full_name": "Jordan Sample", "job_company_name": "Acme"}}))
    out = p.person("Jordan Sample", "Acme")
    assert out["title"] is None and out["start_date"] is None and out["past_employers"] == [] and out["seniority"] == []
    c, _ = make(httpx.Response(200, json={"status": 200, "likelihood": 7, "name": "acme"}))
    out = c.company("Acme", None)
    assert out["industry"] is None and out["employee_count"] is None


def test_low_likelihood_is_no_match_with_note():
    body = json.loads(raw("pdl_person.json"))
    body["likelihood"] = 5
    p, _ = make(httpx.Response(200, json=body))
    assert p.person("Jordan Sample", "Acme") is None
    assert "below the confidence threshold" in p.notes("person")[0]


def test_threshold_is_configurable():
    body = json.loads(raw("pdl_person.json"))
    body["likelihood"] = 5
    p, rec = make(httpx.Response(200, json=body), min_likelihood=4)
    assert p.person("Jordan Sample", "Acme") is not None
    assert dict(rec.requests[0].url.params)["min_likelihood"] == "4"


def test_multiple_matches_is_no_match():
    p, _ = make(httpx.Response(200, json={"status": 200, "likelihood": 9, "data": [{"full_name": "A"}, {"full_name": "B"}]}))
    assert p.person("Jordan Sample", "Acme") is None
    assert "2 possible" in p.notes("person")[0]


def test_404_is_no_match_note():
    p, _ = make(httpx.Response(404, json={"status": 404, "error": {"type": "not_found"}}))
    assert p.company("Nope", None) is None
    assert "no confident company match" in p.notes("company")[0]


@pytest.mark.parametrize("status,word", [(401, "API key"), (402, "limit"), (429, "rate limit"), (503, "unavailable")])
def test_errors_become_notes(status, word):
    p, _ = make(httpx.Response(status, json={"error": "x"}))
    assert p.person("Jordan Sample", "Acme") is None
    assert word in p.notes("person")[0] and "pdl-TESTKEY" not in p.notes("person")[0]


def test_timeout_is_a_note():
    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    p, _ = make(boom)
    assert p.person("Jordan Sample", "Acme") is None
    assert "timed out" in p.notes("person")[0]


@pytest.mark.parametrize("payload", [b"garbage", b"[]", b'{"status":200,"likelihood":9}', b'{"status":200,"likelihood":9,"data":"x"}'])
def test_malformed_is_a_note_not_exception(payload):
    p, _ = make(httpx.Response(200, content=payload))
    assert p.person("Jordan Sample", "Acme") is None
    assert p.notes("person")


def test_feeds_the_researchers():
    prospect = Prospect(prospect_id="p1", name="Jordan Sample", company="Acme Robotics Sample Inc", role="VP Ops", company_domain="acme-robotics.example")

    def route(request):
        return jresp("pdl_person.json") if "person" in request.url.path else jresp("pdl_company.json")

    p, _ = make(route)

    class NoSearch:
        def search(self, q, n):
            return []

    identity, facts, sources, _ = research_person(prospect, NoSearch(), p, Budget())
    assert identity == "confirmed"
    assert any(f.key == "current_role" and "Vp Of Operations" in f.text for f in facts)
    cfacts, csources, _ = research_company(prospect, NoSearch(), p, Budget())
    assert {f.key for f in cfacts} >= {"industry", "employee_count"}
    assert all(s.publisher == "People Data Labs" and s.date == "2026-11-17" for s in sources + csources)

"""Free sources: all tests run offline against fictional fixtures (see free_helpers.py)."""

from __future__ import annotations

import httpx
import pytest
from free_helpers import PUBLIC_IP, SITE, TODAY, FakeNet, html, make_http, resolver_ok

from cold_call_agents.free_sources import build_free_providers
from cold_call_agents.free_sources.edgar import EdgarSource
from cold_call_agents.free_sources.homepage import HomepageSource, is_public_ip
from cold_call_agents.free_sources.http import (
    DEFAULT_USER_AGENT,
    BudgetExhausted,
    HttpClient,
    HttpError,
    user_agent_from_env,
)
from cold_call_agents.free_sources.wikidata import WikidataSource
from cold_call_agents.models import Prospect
from cold_call_agents.orchestrator import Budget, run_research

COMPANY = "Acme Robotics Sample Inc"
SEC_UA = "TestAgent test-contact@example.invalid"  # fake; never a real address


def prospect(**kw) -> Prospect:
    base = dict(prospect_id="p1", name="Jordan Example", company=COMPANY, role="VP Sales")
    return Prospect(**{**base, **kw})


def run(net: FakeNet, env=None, **pkw):
    p = prospect(**pkw)
    llm, search, profiles = build_free_providers(
        p, Budget(), env or {}, http=make_http(net), resolver=resolver_ok, today=TODAY
    )
    return run_research(p, llm=llm, search=search, profiles=profiles, today=TODAY, mode="live"), search


def by_key(b):
    return {f.key: f for f in b.facts}


# ---------------------------------------------------------------- HTTP helper


def test_429_then_success_retries_with_backoff():
    sleeps, n = [], {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(429, headers={"retry-after": "1"}) if n["c"] == 1 else httpx.Response(200, json={"ok": 1})

    http = HttpClient(transport=httpx.MockTransport(handler), sleep=sleeps.append)
    assert http.get_json("https://x.example/a") == {"ok": 1}
    assert n["c"] == 2 and sleeps == [1.0]


def test_persistent_429_gives_up_after_retries():
    http = HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)), sleep=lambda s: None, max_retries=2)
    with pytest.raises(HttpError, match="429"):
        http.get_json("https://x.example/a")
    assert http.requests_made == 3


def test_timeout_is_an_http_error():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    http = HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(HttpError, match="timed out"):
        http.get("https://x.example/a")


def test_request_budget_is_enforced():
    http = HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), max_requests=2)
    http.get_json("https://x.example/1")
    http.get_json("https://x.example/2")
    with pytest.raises(BudgetExhausted):
        http.get_json("https://x.example/3")


def test_user_agent_is_generic_and_contact_is_optional_env():
    seen = []
    http = HttpClient(transport=httpx.MockTransport(lambda r: (seen.append(r.headers["user-agent"]), httpx.Response(200, json={}))[1]))
    http.get_json("https://x.example/")
    assert seen == [DEFAULT_USER_AGENT] and "@" not in DEFAULT_USER_AGENT
    assert user_agent_from_env({}) == DEFAULT_USER_AGENT
    assert "ops-contact" in user_agent_from_env({"RESEARCH_CONTACT": "ops-contact"})


# ---------------------------------------------------------------- Wikidata / Wikipedia


def test_unambiguous_company_match_gives_sourced_structured_facts():
    b, _ = run(FakeNet())
    f = by_key(b)
    assert f["industry"].value == "industrial robotics"
    assert f["headquarters"].value == "Springfield"
    assert f["founded"].value == "1998"
    assert f["official_website"].value == "acme-robotics.example"
    assert f["ceo"].value == "Pat Doe"  # the former CEO (end time set) is excluded
    assert "1,200 employees (as of 2025-12-31)" in f["employee_count"].text
    assert not f["employee_count"].stale  # dated 2025-12-31, within a year of TODAY
    assert "overview" in f
    srcs = {s.id: s for s in b.sources}
    wd = srcs[f["ceo"].source_ids[0]]
    assert wd.publisher == "Wikidata" and wd.url == "https://www.wikidata.org/wiki/Q900001" and wd.date == "2026-09-30"
    emp = srcs[f["employee_count"].source_ids[0]]
    assert emp.date == "2025-12-31" and emp.url.endswith("#P1128")
    wp = srcs[f["overview"].source_ids[0]]
    assert wp.publisher == "Wikipedia" and wp.url == "https://en.wikipedia.org/wiki/Acme_Robotics_Sample"
    # different publishers are independent sources for the verifier
    assert {s.publisher for s in b.sources} >= {"Wikidata", "Wikipedia"}


def test_ambiguous_company_returns_no_wikidata_facts_and_a_note():
    b, _ = run(FakeNet(search="wd_search_ambiguous.json"))
    assert not b.facts or all(f.key not in ("industry", "ceo", "overview") for f in b.facts)
    assert any("single Wikidata organization" in m for m in b.missing)


def test_domain_settles_ambiguity_and_mismatch_refuses():
    net = FakeNet(search="wd_search_ambiguous.json")
    info, _ = WikidataSource(make_http(net)).find_company(COMPANY, "acme-robotics.example")
    assert info and info.qid == "Q900001"
    info, notes = WikidataSource(make_http(FakeNet(search="wd_search_ambiguous.json"))).find_company(COMPANY, "unrelated.example")
    assert info is None and notes


def test_non_organization_entities_are_ignored():
    info, _ = WikidataSource(make_http(FakeNet())).find_company(COMPANY, None)  # search also returns a film
    assert info and info.qid == "Q900001"


def test_wikipedia_prompt_injection_is_sanitized():
    b, _ = run(FakeNet())
    text = " ".join([f.text for f in b.facts] + [s.excerpt for s in b.sources]).lower()
    assert "ignore all previous" not in text and "system prompt" not in text
    assert "warehouse robots" in text  # the legitimate sentence survives


# ---------------------------------------------------------------- person


def test_person_facts_only_on_strong_identity():
    net = FakeNet(search="wd_search_person.json")
    prof = WikidataSource(make_http(net)).person("Pat Doe", COMPANY)
    assert prof and prof["company"] == COMPANY and prof["title"] == "Head of Sample Research"
    assert prof["source"]["url"] == "https://www.wikidata.org/wiki/Q900200"

    b, _ = run(FakeNet(search="wd_search_person.json"), name="Pat Doe")
    assert b.identity_match == "confirmed"
    assert by_key(b)["current_role"].value == "Head of Sample Research"


def test_person_not_found_or_wrong_employer_gives_no_person_facts_and_a_note():
    # Name not in Wikidata at all: the default company search has no human.
    b, _ = run(FakeNet())
    assert b.identity_match == "unsure" and not [f for f in b.facts if f.subject == "person"]
    assert any("No strong public identity match" in m for m in b.missing)
    # Two humans with the same name, only one works at the company -> still strong; but a wrong company is not.
    assert WikidataSource(make_http(FakeNet(search="wd_search_person.json"))).person("Pat Doe", "Some Other Company") is None


def test_person_with_two_matching_candidates_is_refused():
    net = FakeNet(search="wd_search_person_ambiguous.json")
    # Q900201 works at "Some Other Company"; asking for that company finds exactly one -> allowed
    assert WikidataSource(make_http(net)).person("Pat Doe", "Some Other Company")
    # Asking for a company neither works at -> None
    assert WikidataSource(make_http(net)).person("Pat Doe", "Nowhere Ltd") is None


# ---------------------------------------------------------------- EDGAR


def test_edgar_skipped_without_sec_user_agent():
    net = FakeNet()
    b, _ = run(net, env={})
    assert not {h for h in net.hosts() if "sec.gov" in h}
    assert "sic_industry" not in by_key(b)


def test_edgar_facts_and_dated_8k_news_with_user_agent():
    net = FakeNet()
    b, _ = run(net, env={"SEC_USER_AGENT": SEC_UA})
    f = by_key(b)
    assert "General Industrial Machinery" in f["sic_industry"].text
    assert f["sec_business_location"].value == "SPRINGFIELD, IL"
    assert "1 Sample Way" not in " ".join(x.text for x in b.facts)  # street address never used
    assert f["ticker"].value == "ACME"
    news = [x for x in b.facts if x.key.startswith("recent_news")]
    assert len(news) == 2  # the 2024 8-K is outside the window; 9.01-only items are not invented
    assert {x.text for x in news} == {
        "SEC 8-K filed 2026-10-20: results of operations.",
        "SEC 8-K filed 2026-09-01: director or officer change.",
    }
    src = next(s for s in b.sources if "Archives/edgar" in (s.url or ""))
    assert src.publisher == "SEC EDGAR" and src.date in ("2026-10-20", "2026-09-01")
    assert all(r.headers["user-agent"] == SEC_UA for r in net.requests if r.url.host.endswith("sec.gov"))
    # Our own rate stays far below SEC's 10 req/s: only the two calls we need.
    assert sum(1 for h, _ in net.calls if h.endswith("sec.gov")) == 2


def test_edgar_matches_unique_name_without_cik_hint():
    res, _ = EdgarSource(make_http(FakeNet()), SEC_UA, TODAY).lookup(COMPANY, None)
    assert res
    res, _ = EdgarSource(make_http(FakeNet()), SEC_UA, TODAY).lookup("Unknown Co", None)
    assert res == []


def test_edgar_user_agent_is_never_hardcoded():
    import pathlib

    import cold_call_agents.free_sources as pkg

    for p in pathlib.Path(pkg.__file__).parent.glob("*.py"):
        assert "@" not in p.read_text().replace("@dataclass", "").replace("@property", "").replace("@staticmethod", "")


# ---------------------------------------------------------------- homepage safety


def home(net: FakeNet, resolver=resolver_ok, **kw) -> HomepageSource:
    return HomepageSource(make_http(net, **kw), resolver, TODAY)


def test_homepage_extracts_self_description_attributed_and_sanitized():
    net = FakeNet()
    results, notes = home(net).describe(SITE)
    assert not notes and len(results) == 1
    r = results[0]
    c = r.claims[0]
    assert c["label"] == "How the company describes itself"
    assert "not independently verified" in c["text"]
    low = c["text"].lower()
    assert "ignore all previous" not in low and "warehouse robots" in low  # injection sentence dropped
    assert r.publisher == SITE and r.url == f"https://{SITE}/"
    # connects to the validated IP, not a fresh DNS lookup
    assert all(req.url.host == PUBLIC_IP for req in net.requests)


@pytest.mark.parametrize(
    "ips",
    [["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], ["192.168.1.1"], ["::1"], ["fe80::1"], ["100.64.0.1"],
     ["::ffff:127.0.0.1"], ["64:ff9b::7f00:1"], [PUBLIC_IP, "10.0.0.5"], []],
)
def test_private_and_reserved_addresses_are_refused_without_any_request(ips):
    net = FakeNet()
    results, notes = home(net, resolver=lambda h: ips).describe(SITE)
    assert results == [] and notes and "not used" in notes[0]
    assert net.calls == []


def test_is_public_ip():
    assert is_public_ip(PUBLIC_IP) and is_public_ip("2606:4700:4700::1111")
    assert not any(is_public_ip(x) for x in ("0.0.0.0", "224.0.0.1", "240.0.0.1", "not-an-ip"))


@pytest.mark.parametrize("bad", ["127.0.0.1", "http://acme.example", "acme.example:8080", "localhost", "a@b.example", "acme.example/x"])
def test_non_hostname_domains_are_refused(bad):
    net = FakeNet()
    results, notes = home(net).describe(bad)
    assert results == [] and notes and net.calls == []


def test_redirect_to_another_host_is_refused():
    net = FakeNet(over={(SITE, "/"): httpx.Response(302, headers={"location": "https://evil.example/"})})
    results, notes = home(net).describe(SITE)
    assert results == [] and "different host" in notes[0]
    assert "evil.example" not in net.hosts()


def test_redirect_downgrade_to_http_is_refused():
    net = FakeNet(over={(SITE, "/"): httpx.Response(301, headers={"location": f"http://{SITE}/"})})
    results, notes = home(net).describe(SITE)
    assert results == [] and "non-https" in notes[0]


def test_redirect_to_internal_address_literal_is_refused():
    net = FakeNet(over={(SITE, "/"): httpx.Response(302, headers={"location": "https://169.254.169.254/latest"})})
    results, notes = home(net).describe(SITE)
    assert results == [] and notes


def test_redirect_to_www_twin_is_allowed():
    apex = "acme-robotics.example"
    net = FakeNet(over={(apex, "/"): httpx.Response(301, headers={"location": f"https://{SITE}/"}),
                     (apex, "/robots.txt"): httpx.Response(404)})
    results, notes = home(net).describe(apex)
    assert len(results) == 1 and results[0].url == f"https://{SITE}/"


def test_redirect_loop_is_bounded():
    net = FakeNet(over={(SITE, "/"): httpx.Response(302, headers={"location": f"https://{SITE}/"})})
    results, notes = home(net).describe(SITE)
    assert results == [] and "too many redirects" in notes[0]


def test_oversize_body_is_rejected():
    big = httpx.Response(200, content=b"<html>" + b"x" * 1_100_000, headers={"content-type": "text/html"})
    results, notes = home(FakeNet(over={(SITE, "/"): big})).describe(SITE)
    assert results == [] and "too large" in notes[0]


def test_oversize_content_length_header_is_rejected_early():
    big = httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html", "content-length": "5000000"})
    results, notes = home(FakeNet(over={(SITE, "/"): big})).describe(SITE)
    assert results == [] and "too large" in notes[0]


@pytest.mark.parametrize("ctype", ["application/pdf", "application/json", "image/png"])
def test_non_html_is_rejected(ctype):
    resp = httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": ctype})
    results, notes = home(FakeNet(over={(SITE, "/"): resp})).describe(SITE)
    assert results == [] and "content type" in notes[0]


def test_robots_disallow_is_respected():
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /\n", headers={"content-type": "text/plain"})
    net = FakeNet(over={(SITE, "/robots.txt"): robots})
    results, notes = home(net).describe(SITE)
    assert results == [] and "robots.txt" in notes[0]
    assert (SITE, "/") not in net.calls


def test_robots_for_our_agent_token_is_respected_but_other_bots_do_not_matter():
    robots = httpx.Response(200, text="User-agent: SomeOtherBot\nDisallow: /\n", headers={"content-type": "text/plain"})
    results, _ = home(FakeNet(over={(SITE, "/robots.txt"): robots})).describe(SITE)
    assert len(results) == 1


def test_robots_server_error_means_not_fetched():
    net = FakeNet(over={(SITE, "/robots.txt"): httpx.Response(503)})
    results, notes = home(net, max_retries=0).describe(SITE)
    assert results == [] and "robots.txt" in notes[0]


def test_about_page_is_fetched_only_when_homepage_has_no_description():
    net = FakeNet(over={(SITE, "/"): html("homepage_nodesc.html")})
    results, _ = home(net).describe(SITE)
    assert results[0].claims[0]["value"] == "Acme builds robots for logistics teams."
    assert [p for h, p in net.calls if p not in ("/robots.txt",)] == ["/", "/about"]
    net2 = FakeNet()
    home(net2).describe(SITE)
    assert (SITE, "/about") not in net2.calls


def test_phone_number_in_description_is_redacted():
    results, _ = home(FakeNet(over={(SITE, "/"): html("homepage.html")})).describe(SITE)
    # og:description wins; the meta description (with the phone) is only a fallback and is redacted
    only_meta = b'<html><head><meta name="description" content="Robots. Call us at +1 415 555 1234."></head></html>'
    net = FakeNet(over={(SITE, "/"): httpx.Response(200, content=only_meta, headers={"content-type": "text/html"})})
    r2, _ = home(net).describe(SITE)
    assert "415" not in r2[0].claims[0]["text"]


# ---------------------------------------------------------------- end to end


def test_full_run_cites_independent_publishers_for_every_fact():
    b, _ = run(FakeNet(), env={"SEC_USER_AGENT": SEC_UA}, company_domain=SITE)
    assert b.facts and all(f.source_ids for f in b.facts)
    assert {s.publisher for s in b.sources} >= {"Wikidata", "Wikipedia", "SEC EDGAR", SITE}
    assert "SAMPLE" not in b.summary and b.mode == "live"
    assert not b.missing or all("failed" not in m for m in b.missing)


def test_timeouts_give_a_partial_brief_with_missing_notes():
    def boom(req):
        raise httpx.ConnectTimeout("t", request=req)

    net = FakeNet(over={("www.wikidata.org", "/w/api.php"): boom, ("data.sec.gov", "/submissions"): boom})
    b, _ = run(net, env={"SEC_USER_AGENT": SEC_UA}, company_domain=SITE)
    assert any("Wikidata/Wikipedia lookup failed (timed out)" in m for m in b.missing)
    assert any(f.key == "self_description" for f in b.facts)  # the other sources still contributed
    assert not any(f.key == "industry" for f in b.facts)


def test_everything_down_returns_an_empty_but_valid_brief():
    net = FakeNet(over={("www.wikidata.org", "/w/api.php"): httpx.Response(500)})
    b, _ = run(net, company_domain="unreachable.example")
    assert b.facts == [] and b.missing


def test_company_domain_not_used_when_unknown_and_note_added():
    net = FakeNet(search="wd_search_ambiguous.json")
    b, _ = run(net)
    assert any("No company domain known" in m for m in b.missing)
    assert not any(h == SITE for h, _ in net.calls)


def test_request_budget_caps_total_calls():
    net = FakeNet()
    p = prospect(company_domain=SITE)
    http = make_http(net, max_requests=3)
    llm, search, profiles = build_free_providers(p, Budget(), {}, http=http, resolver=resolver_ok, today=TODAY)
    b = run_research(p, llm=llm, search=search, profiles=profiles, today=TODAY)
    assert http.requests_made == 3
    assert any("budget" in m for m in b.missing)

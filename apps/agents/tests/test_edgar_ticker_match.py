"""EDGAR matches an all-caps acronym company name ("IBM") by its exact ticker."""
from cold_call_agents.free_sources import edgar
from cold_call_agents.free_sources.edgar import EdgarSource

ROWS = [
    {"cik_str": 51143, "ticker": "IBM", "title": "INTERNATIONAL BUSINESS MACHINES CORP"},
    {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    {"cik_str": 1, "ticker": "DUP", "title": "DUP ONE INC"},
    {"cik_str": 2, "ticker": "DUP", "title": "DUP TWO INC"},
]


def _client(monkeypatch):
    monkeypatch.setattr(edgar, "_load_tickers", lambda http, ua: ROWS)
    c = EdgarSource.__new__(EdgarSource)
    c.http, c.ua = None, "test agent test@example.com"
    return c


def _name_cik(monkeypatch, company):
    c = _client(monkeypatch)
    monkeypatch.setattr(EdgarSource, "_submissions", lambda self, cik: None, raising=False)
    try:
        c.lookup(company, None)
    except Exception:
        pass  # submissions fetch is out of scope; match is set before it
    return c.match["name_cik"]


def test_acronym_matches_unique_ticker(monkeypatch):
    assert _name_cik(monkeypatch, "IBM") == 51143


def test_mixed_case_or_unknown_does_not_match_ticker(monkeypatch):
    assert _name_cik(monkeypatch, "Ibm") is None
    assert _name_cik(monkeypatch, "ZZZZ") is None


def test_ambiguous_ticker_is_not_matched(monkeypatch):
    assert _name_cik(monkeypatch, "DUP") is None

"""SEC EDGAR: public-company facts from company_tickers.json and submissions.

Needs SEC_USER_AGENT (SEC requires a descriptive User-Agent with contact info).
It is read from the environment only; if unset the whole source is skipped.
We only use structured fields (SIC description, city/state, filing metadata).
We deliberately do not use the street address (guardrails treat it as private).
"""

from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from typing import Any, Optional

from ..providers import SearchResult
from ..researchers import normalize_company
from .http import HttpClient, HttpError

log = logging.getLogger("cold_call_agents.free_sources.edgar")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
NEWS_WINDOW = timedelta(days=365)
MAX_NEWS = 3
# 8-K item numbers -> plain-language topic. Items not listed here are skipped
# (e.g. 9.01 exhibits) so we never print a filing title we did not derive.
ITEMS = {
    "1.01": "entry into a material agreement",
    "1.05": "material cybersecurity incident",
    "2.01": "completion of an acquisition or disposition",
    "2.02": "results of operations",
    "2.05": "exit or restructuring costs",
    "5.02": "director or officer change",
    "5.07": "shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "other events",
}

_warned = False
_tickers_cache: Optional[tuple[float, list[dict]]] = None
_cache_lock = threading.Lock()


def edgar_user_agent(env: dict[str, str]) -> Optional[str]:
    """SEC_USER_AGENT, or None (logging once) so EDGAR is skipped entirely."""
    global _warned
    ua = (env.get("SEC_USER_AGENT") or "").strip()
    if not ua and not _warned:
        _warned = True
        log.warning("SEC_USER_AGENT is not set; skipping SEC EDGAR lookups.")
    return ua or None


def _load_tickers(http: HttpClient, ua: str) -> list[dict]:
    global _tickers_cache
    import time

    with _cache_lock:
        if _tickers_cache and time.monotonic() - _tickers_cache[0] < 86400:
            return _tickers_cache[1]
    data = http.get_obj(TICKERS_URL, user_agent=ua, max_bytes=5_000_000)
    rows = [r for r in data.values() if isinstance(r, dict) and str(r.get("cik_str", "")).isdigit()]
    with _cache_lock:
        _tickers_cache = (time.monotonic(), rows)
    return rows


class EdgarSource:
    def __init__(self, http: HttpClient, user_agent: str, today: Optional[date] = None) -> None:
        self.http = http
        self.ua = user_agent
        self.today = today or date.today()
        self.match: dict[str, Any] = {}

    def lookup(self, company: str, cik_hint: Optional[str]) -> tuple[list[SearchResult], list[str]]:
        """Return (results, notes). Match by CIK (from Wikidata) or a unique exact name.

        After the call, `self.match` describes the match: the matched `cik`, its `title`,
        and `name_cik`, the CIK found by exact name alone (None if none or ambiguous).
        """
        rows = _load_tickers(self.http, self.ua)
        want = normalize_company(company)
        named = {int(r["cik_str"]): str(r.get("title", "")) for r in rows if want and normalize_company(str(r.get("title", ""))) == want}
        name_cik = next(iter(named)) if len(named) == 1 else None
        cik: Optional[int] = None
        if cik_hint and cik_hint.isdigit():
            if any(int(r["cik_str"]) == int(cik_hint) for r in rows):
                cik = int(cik_hint)
        else:
            cik = name_cik
        titles = {int(r["cik_str"]): str(r.get("title", "")) for r in rows}
        self.match = {"cik": cik, "title": titles.get(cik, "") if cik else "", "name_cik": name_cik}
        if cik is None:
            return [], []  # not a US-listed company we can match; not worth a note
        sub = self.http.get_obj(SUBMISSIONS_URL.format(cik=cik), user_agent=self.ua)
        return self._results(cik, sub), []

    def _results(self, cik: int, sub: dict[str, Any]) -> list[SearchResult]:
        name = str(sub.get("name") or "")
        page = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}"
        claims: list[dict[str, str]] = []

        def add(key: str, label: str, text: str, value: str) -> None:
            claims.append({"subject": "company", "key": key, "label": label, "text": text, "value": value})

        sic = str(sub.get("sicDescription") or "").strip()
        if sic:
            code = str(sub.get("sic") or "").strip()
            add("sic_industry", "Industry (SEC SIC code)", f"SEC industry classification: {sic}" + (f" (SIC {code})." if code else "."), sic)
        biz = (sub.get("addresses") or {}).get("business") or {}
        place = ", ".join(p for p in (biz.get("city"), biz.get("stateOrCountry")) if p)
        if place:
            add("sec_business_location", "Business location (SEC filings)", f"Business location in SEC filings: {place}.", place)
        tickers, exch = sub.get("tickers") or [], sub.get("exchanges") or []
        if tickers:
            add("ticker", "Stock ticker", f"Publicly traded as {tickers[0]}" + (f" ({exch[0]})." if exch else "."), tickers[0])

        recent = (sub.get("filings") or {}).get("recent") or {}
        rows = [
            {k: (recent.get(k) or [None] * n)[i] for k in ("form", "filingDate", "accessionNumber", "primaryDocument", "items")}
            for n in [len(recent.get("form") or [])]
            for i in range(n)
        ]
        latest = next((r for r in rows if r["form"] in ("10-K", "10-Q")), None)
        if latest and latest["filingDate"]:
            add("latest_periodic_report", "Latest periodic report", f"Latest {latest['form']} filed {latest['filingDate']}.", f"{latest['form']} {latest['filingDate']}")

        results = []
        if claims:
            results.append(SearchResult(
                title=f"{name or 'Company'} filings on SEC EDGAR", url=page, publisher="SEC EDGAR",
                published_date=latest["filingDate"] if latest else None,
                content=f"SEC EDGAR submissions record for {name}.", claims=claims,
            ))
        results.extend(self._news(cik, rows))
        return results

    def _news(self, cik: int, rows: list[dict]) -> list[SearchResult]:
        out = []
        for r in rows:
            if r["form"] != "8-K" or not r["filingDate"] or len(out) >= MAX_NEWS:
                continue
            try:
                filed = date.fromisoformat(r["filingDate"])
            except ValueError:
                continue
            if self.today - filed > NEWS_WINDOW:
                continue
            topics = [ITEMS[i.strip()] for i in str(r["items"] or "").split(",") if i.strip() in ITEMS]
            acc = str(r["accessionNumber"] or "")
            doc = str(r["primaryDocument"] or "")
            if not topics or not acc or not doc:
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            text = f"SEC 8-K filed {r['filingDate']}: {', '.join(topics)}."
            out.append(SearchResult(
                title=f"Form 8-K filed {r['filingDate']}", url=url, publisher="SEC EDGAR",
                published_date=r["filingDate"], content=text,
                claims=[{"subject": "company", "key": f"recent_news.8k_{acc.replace('-', '')}",
                         "label": "Recent SEC filing", "text": text, "value": text}],
            ))
        return out

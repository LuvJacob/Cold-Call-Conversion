"""Wikidata + Wikipedia: structured company facts, plus strong-match person lookup.

Facts come from Wikidata claims (deterministic, no LLM). The Wikipedia REST
summary is used as a source excerpt. If the company name matches more than one
organization and the domain does not settle it, we return nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from ..researchers import normalize_company
from ..providers import SearchResult
from .http import HttpClient, HttpError

API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
# An entity counts as an organization only if it has at least one of these
# (industry, HQ, employees, ticker, stock exchange, parent, legal form, SEC CIK, CEO).
ORG_PROPS = ("P452", "P159", "P1128", "P249", "P414", "P749", "P1454", "P5531", "P169")


@dataclass
class CompanyInfo:
    qid: str
    label: str
    url: str
    modified: Optional[str]
    website: Optional[str] = None
    cik: Optional[str] = None
    profile: dict[str, Any] = field(default_factory=dict)  # industry (+ source), for the ProfileClient path
    results: list[SearchResult] = field(default_factory=list)


def _same_name(a: str, b: str) -> bool:
    na, nb = normalize_company(a), normalize_company(b)
    return bool(na) and na == nb


def _values(entity: dict, prop: str) -> list[dict]:
    """Non-deprecated claims for a property; only preferred ones if any exist."""
    claims = [c for c in entity.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"]
    preferred = [c for c in claims if c.get("rank") == "preferred"]
    return preferred or claims


def _datavalue(claim: dict) -> Any:
    snak = claim.get("mainsnak", {})
    return snak.get("datavalue", {}).get("value") if snak.get("snaktype") == "value" else None


def _item_ids(entity: dict, prop: str, current_only: bool = False) -> list[str]:
    out = []
    for c in _values(entity, prop):
        if current_only and c.get("qualifiers", {}).get("P582"):  # has an end time
            continue
        v = _datavalue(c)
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def _time(value: Any) -> tuple[Optional[str], int]:
    """Wikidata time value -> (ISO date or None, precision)."""
    if not isinstance(value, dict):
        return None, 0
    m = re.match(r"^[+-](\d{4})-(\d\d)-(\d\d)", str(value.get("time", "")))
    if not m:
        return None, 0
    y, mo, d = m.groups()
    return f"{y}-{mo if mo != '00' else '01'}-{d if d != '00' else '01'}", int(value.get("precision", 0))


def _label(entity: dict) -> str:
    return entity.get("labels", {}).get("en", {}).get("value", "")


def _names(entity: dict) -> list[str]:
    return [_label(entity), *[a.get("value", "") for a in entity.get("aliases", {}).get("en", [])]]


def _host(url: str) -> str:
    try:
        host = (urlsplit(url if "//" in url else f"//{url}").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def domains_match(a: str, b: str) -> bool:
    """Same site, allowing a subdomain on either side (careers.ibm.com ~ ibm.com)."""
    ha, hb = _host(a), _host(b)
    return bool(ha and hb) and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha))


class WikidataSource:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    # -- API calls ------------------------------------------------------
    def _search(self, name: str) -> list[str]:
        data = self.http.get_obj(
            API,
            params={"action": "wbsearchentities", "search": name, "language": "en",
                    "type": "item", "limit": "7", "format": "json"},
        )
        return [r["id"] for r in data.get("search", []) if r.get("id")]

    def _entities(self, ids: list[str], props: str) -> dict[str, dict]:
        if not ids:
            return {}
        data = self.http.get_obj(
            API,
            params={"action": "wbgetentities", "ids": "|".join(ids[:50]), "props": props,
                    "languages": "en", "sitefilter": "enwiki", "format": "json"},
        )
        return data.get("entities", {})

    def _labels(self, ids: list[str]) -> dict[str, str]:
        ids = list(dict.fromkeys(ids))
        ents = self._entities(ids, "labels")
        return {i: _label(e) for i, e in ents.items() if _label(e)}

    # -- company ----------------------------------------------------------
    def find_company(self, name: str, domain: Optional[str]) -> tuple[Optional[CompanyInfo], list[str]]:
        """Return (company, notes). Company is None unless exactly one entity fits."""
        notes: list[str] = []
        ids = self._search(name)
        ents = self._entities(ids, "claims|labels|aliases|sitelinks|info")
        cands = []
        for qid in ids:
            e = ents.get(qid)
            if not e or "Q5" in _item_ids(e, "P31"):  # people are not companies
                continue
            if not any(_values(e, p) for p in ORG_PROPS):
                continue
            if any(_same_name(n, name) for n in _names(e) if n):
                cands.append(e)
        chosen = self._choose(cands, domain)
        if chosen is None:
            notes.append(
                "Company could not be matched to a single Wikidata organization, so Wikidata/Wikipedia facts were left out."
                if cands
                else "No Wikidata organization matched the company name."
            )
            return None, notes
        return self._build(chosen), notes

    @staticmethod
    def _choose(cands: list[dict], domain: Optional[str]) -> Optional[dict]:
        def sites(e: dict) -> list[str]:
            return [v for c in _values(e, "P856") if isinstance(v := _datavalue(c), str)]

        if domain:
            hits = [e for e in cands if any(domains_match(s, domain) for s in sites(e))]
            if len(hits) == 1:
                return hits[0]
            if hits:
                return None
            # No domain match: accept only a lone candidate with no website to contradict it.
            blank = [e for e in cands if not sites(e)]
            return blank[0] if len(cands) == 1 and len(blank) == 1 else None
        return cands[0] if len(cands) == 1 else None

    def _build(self, e: dict) -> CompanyInfo:
        qid = e["id"]
        modified = (e.get("modified") or "")[:10] or None
        info = CompanyInfo(qid=qid, label=_label(e), url=f"https://www.wikidata.org/wiki/{qid}", modified=modified)
        sites = [v for c in _values(e, "P856") if isinstance(v := _datavalue(c), str)]
        info.website = sites[0] if sites else None
        ciks = [v for c in _values(e, "P5531") if isinstance(v := _datavalue(c), str) and v.isdigit()]
        info.cik = ciks[0] if ciks else None

        ref_ids = {p: _item_ids(e, p, current_only=p == "P169") for p in ("P452", "P159", "P169", "P749")}
        labels = self._labels([i for ids in ref_ids.values() for i in ids])

        def names(prop: str, limit: int = 3) -> list[str]:
            return [labels[i] for i in ref_ids[prop] if i in labels][:limit]

        src = {"title": f"{info.label} (Wikidata {qid})", "publisher": "Wikidata", "url": info.url, "date": modified}
        industry = names("P452")
        if industry:
            info.profile["industry"] = "; ".join(industry)
        emp = self._employees(e)
        if emp:
            count, day = emp
            when = f" (as of {day})" if day else ""
            info.results.append(
                SearchResult(
                    title=f"{info.label}: employees (Wikidata {qid})", url=f"{info.url}#P1128",
                    publisher="Wikidata", published_date=day or modified,
                    content=f"Employee count for {info.label} from Wikidata.",
                    claims=[{"subject": "company", "key": "employee_count", "label": "Company size",
                             "text": f"About {count:,} employees{when}.", "value": str(count)}],
                )
            )
        info.profile["source"] = src

        claims: list[dict[str, str]] = []

        def add(key: str, label: str, text: str, value: str) -> None:
            claims.append({"subject": "company", "key": key, "label": label, "text": text, "value": value})

        if names("P159", 1):
            add("headquarters", "Headquarters", f"Headquarters: {names('P159', 1)[0]}.", names("P159", 1)[0])
        for c in _values(e, "P571")[:1]:
            day, prec = _time(_datavalue(c))
            if day:
                when = day[:4] if prec <= 9 else day
                add("founded", "Founded", f"Founded {when}.", when)
        if info.website:
            add("official_website", "Official website", f"Official website: {info.website}.", _host(info.website))
        if names("P169", 1):
            add("ceo", "CEO", f"CEO: {names('P169', 1)[0]}.", names("P169", 1)[0])
        if names("P749", 1):
            add("parent_organization", "Parent organization", f"Parent organization: {names('P749', 1)[0]}.", names("P749", 1)[0])
        if claims:
            info.results.append(
                SearchResult(
                    title=src["title"], url=info.url, publisher="Wikidata", published_date=modified,
                    content=f"Structured data for {info.label} from Wikidata.", claims=claims,
                )
            )
        title = e.get("sitelinks", {}).get("enwiki", {}).get("title")
        if title:
            wp = self._wikipedia(title)
            if wp:
                info.results.append(wp)
        return info

    @staticmethod
    def _employees(e: dict) -> Optional[tuple[int, Optional[str]]]:
        best: Optional[tuple[str, int]] = None
        undated: Optional[int] = None
        for c in _values(e, "P1128"):
            v = _datavalue(c)
            try:
                n = int(float(v["amount"]))
            except (TypeError, KeyError, ValueError):
                continue
            pit = c.get("qualifiers", {}).get("P585", [])
            day = _time(pit[0].get("datavalue", {}).get("value"))[0] if pit else None
            if day and (best is None or day > best[0]):
                best = (day, n)
            elif not day and undated is None:
                undated = n
        if best:
            return best[1], best[0]
        return (undated, None) if undated is not None else None

    def _wikipedia(self, title: str) -> Optional[SearchResult]:
        try:
            data = self.http.get_obj(WIKIPEDIA_SUMMARY + quote(title.replace(" ", "_"), safe=""))
        except HttpError:
            return None  # the Wikidata facts still stand
        extract = (data.get("extract") or "").strip()
        if data.get("type") == "disambiguation" or not extract:
            return None
        page = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page")
        first = re.split(r"(?<=[.!?])\s+", extract)
        overview = " ".join(first[:2])[:300]
        return SearchResult(
            title=f"{data.get('title') or title} (Wikipedia)", url=page, content=extract,
            published_date=(data.get("timestamp") or "")[:10] or None, publisher="Wikipedia",
            claims=[{"subject": "company", "key": "overview", "label": "Overview (Wikipedia)",
                     "text": overview, "value": ""}],
        )

    # -- person -----------------------------------------------------------
    def person(self, name: str, company: str) -> Optional[dict[str, Any]]:
        """A profile only when exactly one human has this exact name AND a
        current employer matching the company. Otherwise None (never guess)."""
        ids = self._search(name)
        ents = self._entities(ids, "claims|labels|aliases|info")
        humans = [
            e for i in ids
            if (e := ents.get(i)) and "Q5" in _item_ids(e, "P31")
            and any(" ".join(n.lower().split()) == " ".join(name.lower().split()) for n in _names(e) if n)
        ]
        if not humans:
            return None
        labels = self._labels([i for e in humans for i in _item_ids(e, "P108", True)])
        strong = [
            e for e in humans
            if any(_same_name(labels.get(i, ""), company) for i in _item_ids(e, "P108", True))
        ]
        if len(strong) != 1:
            return None
        e = strong[0]
        employer = next(labels[i] for i in _item_ids(e, "P108", True) if _same_name(labels.get(i, ""), company))
        roles = self._labels(_item_ids(e, "P39", True))
        title = next(iter(roles.values()), "")
        url = f"https://www.wikidata.org/wiki/{e['id']}"
        return {
            "name": _label(e), "company": employer, "title": title,
            "source": {"title": f"{_label(e)} (Wikidata {e['id']})", "publisher": "Wikidata",
                       "url": url, "date": (e.get("modified") or "")[:10] or None},
        }

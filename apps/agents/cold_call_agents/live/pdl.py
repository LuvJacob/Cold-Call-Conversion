"""People Data Labs as a ProfileClient.

APIs relied on (docs: https://docs.peopledatalabs.com/docs/input-parameters-person-enrichment-api,
https://docs.peopledatalabs.com/docs/output-response-person-enrichment-api,
https://docs.peopledatalabs.com/docs/input-parameters-company-enrichment-api,
https://docs.peopledatalabs.com/docs/fields, https://docs.peopledatalabs.com/docs/company-schema):
  GET https://api.peopledatalabs.com/v5/person/enrich?name=..&company=..&min_likelihood=N&titlecase=true
  GET https://api.peopledatalabs.com/v5/company/enrich?name=..&website=..&min_likelihood=N&titlecase=true
  Header: X-Api-Key: <PDL_API_KEY>
  200: {"status": 200, "likelihood": 1-10, "data": {...}}. No match is an HTTP 404.
  Person data fields we read: full_name, job_title, job_title_levels[], job_company_name,
    job_start_date ("2015-03"), experience[{company:{name}, title:{name}, is_primary, end_date}].
  Company data fields we read: name/display_name, website, industry, employee_count, size ("11-50"),
    location.locality (HQ city), founded (year).
`min_likelihood` is sent so PDL does not return (or bill) weak matches, and the score is checked
again here. A `data` list (several matches) is treated as no match.

Privacy: fields are read from an allowlist only. Personal emails, phones, home addresses and
birth data are never read, stored or returned (the models have no field for them).
Failures and no-matches become notes (`notes(subject)`), never exceptions.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Callable, Mapping, Optional

import httpx

from ..free_sources.http import HttpError
from ..guardrails import sanitize_web_text
from .dates import parse_date
from .http import LiveHttp, status_note
from .models import CompanyProfile, PersonProfile

PERSON_URL = "https://api.peopledatalabs.com/v5/person/enrich"
COMPANY_URL = "https://api.peopledatalabs.com/v5/company/enrich"
NAME = "People Data Labs"
DEFAULT_MIN_LIKELIHOOD = 6
MAX_PAST_EMPLOYERS = 5


def _s(value: Any, n: int = 120) -> Optional[str]:
    if not isinstance(value, str):
        return None
    out = sanitize_web_text(value, n, redact=True)
    return out or None


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class PdlProfiles:
    """Implements ProfileClient."""

    def __init__(
        self,
        api_key: str,
        http: LiveHttp,
        *,
        min_likelihood: int = DEFAULT_MIN_LIKELIHOOD,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._key = api_key
        self.http = http
        self.min_likelihood = min_likelihood
        self._today = today
        self._notes: dict[str, list[str]] = {"person": [], "company": []}
        self._lock = threading.Lock()

    def close(self) -> None:
        self.http.close()

    def notes(self, subject: str) -> list[str]:
        return list(dict.fromkeys(self._notes.get(subject, [])))

    def add_note(self, text: str) -> None:
        for v in self._notes.values():
            v.append(text)

    def _note(self, subject: str, text: str) -> None:
        with self._lock:
            self._notes[subject].append(text)

    # -- shared fetch ---------------------------------------------------------
    def _fetch(self, subject: str, url: str, params: dict[str, str]) -> Optional[tuple[dict, int]]:
        """Returns (data, likelihood) for one confident match, else None with a note."""
        label = f"{NAME} {subject} lookup"
        try:
            resp = self.http.get(url, params={**params, "min_likelihood": str(self.min_likelihood), "titlecase": "true"},
                                 headers={"X-Api-Key": self._key})
        except HttpError as exc:
            self._note(subject, f"{label} failed ({exc}).")
            return None
        if resp.status == 404:
            self._note(subject, f"{NAME} found no confident {subject} match.")
            return None
        if resp.status != 200:
            self._note(subject, status_note(NAME, resp.status))
            return None
        try:
            body = resp.json()
            # Person enrich wraps the record in "data"; company enrich returns fields flat.
            data = body["data"] if "data" in body else {k: v for k, v in body.items() if k != "status"}
            likelihood = body.get("likelihood", data.get("likelihood") if isinstance(data, dict) else None)
        except (ValueError, KeyError, TypeError, AttributeError):
            self._note(subject, f"{label} returned an unexpected response.")
            return None
        if isinstance(data, list):
            if len(data) != 1:
                self._note(subject, f"{NAME} returned {len(data)} possible {subject} matches, so none was used.")
                return None
            data = data[0]
            if isinstance(data, dict) and likelihood is None:
                likelihood = data.get("likelihood")
        if not isinstance(data, dict):
            self._note(subject, f"{label} returned an unexpected response.")
            return None
        if not isinstance(likelihood, int) or isinstance(likelihood, bool) or likelihood < self.min_likelihood:
            self._note(
                subject,
                f"{NAME} {subject} match was below the confidence threshold "
                f"(likelihood {likelihood if isinstance(likelihood, int) else 'unknown'}, need {self.min_likelihood}), so it was not used.",
            )
            return None
        return data, likelihood

    # -- ProfileClient -------------------------------------------------------
    def person(self, name: str, company: str) -> Optional[dict[str, Any]]:
        got = self._fetch("person", PERSON_URL, {"name": name, "company": company})
        if not got:
            return None
        data, likelihood = got
        full_name, employer = _s(data.get("full_name")), _s(data.get("job_company_name"))
        if not (full_name and employer):
            self._note("person", f"{NAME} person record lacked a name or current employer, so it was not used.")
            return None
        past: list[str] = []
        for e in data.get("experience") or []:
            comp = e.get("company") if isinstance(e, Mapping) else None
            n = _s(comp.get("name")) if isinstance(comp, Mapping) else None
            if n and not e.get("is_primary") and n.lower() != employer.lower() and n not in past:
                past.append(n)
        levels = data.get("job_title_levels")
        profile = PersonProfile(
            name=full_name,
            title=_s(data.get("job_title")),
            company=employer,
            seniority=[x for x in (_s(v, 40) for v in levels) if x] if isinstance(levels, list) else [],
            start_date=parse_date(data.get("job_start_date")),
            past_employers=past[:MAX_PAST_EMPLOYERS],
            likelihood=likelihood,
            as_of=self._today().isoformat(),
        )
        return profile.to_profile_dict()

    def company(self, name: str, domain: Optional[str]) -> Optional[dict[str, Any]]:
        params = {"name": name}
        if domain:
            params["website"] = domain
        got = self._fetch("company", COMPANY_URL, params)
        if not got:
            return None
        data, likelihood = got
        label = _s(data.get("display_name")) or _s(data.get("name"))
        if not label:
            self._note("company", f"{NAME} company record had no name, so it was not used.")
            return None
        loc = data.get("location")
        profile = CompanyProfile(
            name=label,
            website=_s(data.get("website"), 100),
            industry=_s(data.get("industry"), 100),
            employee_count=_int(data.get("employee_count")),
            size_range=_s(data.get("size"), 20),
            hq_city=_s(loc.get("locality"), 80) if isinstance(loc, Mapping) else None,
            founded=_int(data.get("founded")),
            likelihood=likelihood,
            as_of=self._today().isoformat(),
        )
        return profile.to_profile_dict()


def build_pdl(
    api_key: str, deadline: float, *, min_likelihood: int = DEFAULT_MIN_LIKELIHOOD,
    transport: Optional[httpx.BaseTransport] = None, today: Callable[[], date] = date.today, **kw: Any,
) -> PdlProfiles:
    http = LiveHttp(max_requests=8, deadline_seconds=deadline, timeout=15.0, max_retries=1, transport=transport, **kw)
    return PdlProfiles(api_key, http, min_likelihood=min_likelihood, today=today)

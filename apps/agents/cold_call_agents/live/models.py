"""Typed profiles for the People Data Labs client.

Only non-private professional fields exist here. There is deliberately no
field for emails, phones, home addresses or birth data, so they cannot leak.
`to_profile_dict()` gives the plain-dict shape the researchers read.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

PDL_PUBLISHER = "People Data Labs"


def _source(title: str, as_of: Optional[str], note: str) -> dict[str, Any]:
    return {"title": title, "publisher": PDL_PUBLISHER, "url": None, "date": as_of, "note": note}


class PersonProfile(BaseModel):
    name: str
    title: Optional[str] = None
    company: str
    seniority: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None  # when the current role began (ISO date)
    past_employers: list[str] = Field(default_factory=list)
    likelihood: int = 0
    as_of: Optional[str] = None  # ISO date the provider record was retrieved

    def to_profile_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "company": self.company,
            "title": self.title,
            "start_date": self.start_date,
            "seniority": self.seniority,
            "past_employers": self.past_employers,
            "source": _source("People Data Labs person record", self.as_of, "provider record; underlying data date unknown"),
        }


class CompanyProfile(BaseModel):
    name: str
    website: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    size_range: Optional[str] = None
    hq_city: Optional[str] = None
    founded: Optional[int] = None
    likelihood: int = 0
    as_of: Optional[str] = None

    def to_profile_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.website,
            "industry": self.industry,
            "employee_count": self.employee_count if self.employee_count is not None else self.size_range,
            "hq_city": self.hq_city,
            "founded": self.founded,
            "website": self.website,
            "source": _source("People Data Labs company record", self.as_of, "provider record; underlying data date unknown"),
        }

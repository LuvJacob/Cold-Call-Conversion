"""Round 3: structural rules (sentence begins with the subject, one person, no other org,
past/hedge markers on every key, year checks, combined excerpts, NFC)."""

import json
import unicodedata

import pytest

from cold_call_agents.extraction import Extractor, Subject, combine_excerpts
from cold_call_agents.models import Prospect
from cold_call_agents.providers import MockProfiles, MockSearch, SearchResult
from cold_call_agents.researchers import Budget, research_company

JANE = Subject("person", "Jane Doe", "Acme Inc")
ACME = Subject("company", "Acme")


class Fake:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt):
        return json.dumps(self.reply)


def kept(subject, page, key, value, date="2026-01-01"):
    ex = Extractor(Fake([{"key": key, "value": value, "quote": page}]))
    return ex.extract(SearchResult("t", "https://e.com/a", page, date, "P"), subject)


@pytest.mark.parametrize(
    "subject,page,key,value",
    [
        (JANE, "Jane Doe is the CEO of Globex.", "current_role", "CEO"),
        (JANE, "Jane Doe thanked CEO Mark Lee.", "current_role", "CEO"),
        (JANE, "Jane Doe thanked Bob, CEO of Acme Inc.", "current_role", "CEO"),
        (ACME, "Acme competes with Globex, which employs 650 people.", "employee_count", "650"),
        (ACME, "Acme acquired Globex, a software firm based in Austin.", "headquarters", "Austin"),
        (ACME, "Acme acquired Globex, a software firm based in Austin.", "industry", "software"),
        (JANE, "Jane Doe served as VP of Sales at Acme Inc.", "current_role", "VP of Sales"),
        (JANE, "Jane Doe is interim VP of Sales at Acme Inc.", "current_role", "VP of Sales"),
        (JANE, "Jane Doe is VP of Sales at Acme Inc from 2015 to 2019.", "current_role", "VP of Sales"),
        (JANE, "Jane Doe is VP of Sales at Acme Inc (2015-2019).", "current_role", "VP of Sales"),
        (JANE, "Jane Doe is VP of Sales at Acme Inc as of 2019.", "current_role", "VP of Sales"),
        (ACME, "Acme reportedly employs 650 people.", "employee_count", "650"),
        (ACME, "Acme may open a plant.", "recent_news.x", "plant"),
        (ACME, "Acme is no longer based in Ohio.", "headquarters", "Ohio"),
    ],
)
def test_dropped(subject, page, key, value):
    assert kept(subject, page, key, value) == []


def test_still_kept():
    assert kept(JANE, "Jane Doe is VP of Sales at Acme Inc.", "current_role", "VP of Sales")
    assert kept(JANE, "In 2026, Jane Doe is VP of Sales at Acme Inc.", "current_role", "VP of Sales")
    assert kept(ACME, "Acme's headquarters are in Ohio.", "headquarters", "Ohio")  # possessive ok for companies
    assert kept(ACME, "Acme is headquartered in Ohio.", "headquarters", "Ohio")
    assert kept(ACME, "Last year, Acme opened a plant.", "recent_news.x", "plant")


def test_year_check_needs_source_date():
    page = "Jane Doe is VP of Sales at Acme Inc as of 2019."
    assert kept(JANE, page, "current_role", "VP of Sales", date=None)


def test_nfc_normalization_matches_decomposed_name():
    name = unicodedata.normalize("NFD", "José García")
    page = f"{name} is Director of Ops at Acme Inc."
    subj = Subject("person", "José García", "Acme Inc")
    assert kept(subj, page, "current_role", "Director of Ops")


def test_combine_excerpts():
    a = {"text": "A sentence.", "excerpt": "Before. A sentence. After."}
    b = {"text": "B sentence.", "excerpt": "More. B sentence. End."}
    out = combine_excerpts([a, b])
    assert "A sentence." in out and "B sentence." in out
    big = {"text": "x" * 290, "excerpt": "y" * 300}
    assert len(combine_excerpts([big, dict(big, excerpt="z" * 300, text="w" * 290), dict(big, excerpt="q" * 300)])) <= 600


def test_multiple_claims_cited_excerpt_covers_each_sentence():
    s1 = "Northwind Logistics employs about 650 people across two plants."
    s2 = "Northwind Logistics is headquartered in Port Example."
    page = "Intro. " * 30 + s1 + " " + "Middle text. " * 30 + s2 + " Outro."
    search = MockSearch([{"title": "t", "url": "https://example.com/a", "content": page, "publisher": "W",
                          "published_date": "2026-09-01", "keywords": ["northwind"]}])
    llm = Fake([
        {"key": "employee_count", "value": "650", "quote": s1},
        {"key": "headquarters", "value": "Port Example", "quote": s2},
    ])
    prospect = Prospect(prospect_id="p", name="Dana Reyes", company="Northwind Logistics", role="VP")
    facts, sources, _ = research_company(prospect, search, MockProfiles(None, None), Budget(), llm)
    assert {f.key for f in facts} >= {"employee_count", "headquarters"}
    src = sources[0]
    assert "650 people" in src.excerpt and "Port Example" in src.excerpt


def test_value_cannot_carry_wrong_employer():
    """Reviewer round 3: 'CEO of Globex' for an Acme prospect must be dropped."""
    assert kept(JANE, "Jane Doe is the CEO of Globex.", "current_role", "CEO of Globex") == []
    assert kept(JANE, "Jane Doe is the VP of Sales at Globex.", "current_role", "VP of Sales at Globex") == []
    assert kept(JANE, "Jane Doe is CEO of Acme Inc.", "current_role", "CEO of Acme Inc")

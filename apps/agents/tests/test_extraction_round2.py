"""Round 2 adversarial tests for the stricter extraction rules.

Formerly strict xfails: false facts that got through and recall bugs, now fixed.
"""

import json

import pytest

from cold_call_agents.extraction import Extractor, Subject
from cold_call_agents.providers import SearchResult


class Fake:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt):
        return json.dumps(self.reply)


def kept(subject, page, key, value, quote=None):
    ex = Extractor(Fake([{"key": key, "value": value, "quote": quote or page}]))
    return ex.extract(SearchResult("t", "https://e.com/a", page, "2026-01-01", "P"), subject)


JANE = Subject("person", "Jane Doe", "Acme Inc")
ACME = Subject("company", "Acme Inc")


# ---- held ----------------------------------------------------------------

@pytest.mark.parametrize(
    "page,key,value,subject",
    [
        ("Acme's Jane Doe, the VP of Sales at Globex, spoke.", "current_role", "VP of Sales", JANE),
        ("Jane Doe is the VP of Sales at Globex.", "current_role", "VP of Sales", JANE),
        ("Jane Doe joined Acme in 2019 as VP of Sales; she left in 2023.", "current_role", "VP of Sales", JANE),
        ("Mary-Jane Doe is CEO of Acme Inc.", "current_role", "CEO", JANE),
        ("Jane Doe's brother is the CEO of Acme Inc.", "current_role", "CEO", JANE),
        ("Jane Doe was replaced as VP of Sales at Acme Inc.", "current_role", "VP of Sales", JANE),
        ("Acme Inc has about 650 employees worldwide, up from 400.", "employee_count", "650", ACME),
        ("Acme Inc has 650 customers and employees.", "employee_count", "650", ACME),
        ("Each square employs 650 people in the market.", "employee_count", "650", Subject("company", "Square")),
        ("We target 650 employees for training.", "employee_count", "650", Subject("company", "Target")),
        ("Globex is headquartered in Texas. Acme Inc is in Ohio.", "headquarters", "Texas", ACME),
    ],
)
def test_held(page, key, value, subject):
    assert kept(subject, page, key, value) == []


def test_true_facts_kept():
    assert kept(JANE, "Jane Doe is VP of Sales at Acme Inc.", "current_role", "VP of Sales")
    assert kept(ACME, "acme inc employs 650 people.", "employee_count", "650")
    assert kept(Subject("person", "José García", "Acme Inc"), "José García is Director of Ops at Acme Inc.", "current_role", "Director of Ops")
    assert kept(ACME, "Acme Inc has 6,500 employees.", "employee_count", "6,500")
    assert kept(Subject("company", "Box"), "Box employs 650 people.", "employee_count", "650")


# ---- false facts that get through ------------------------------------------

def test_semicolon_split_hides_departure():
    page = "Jane Doe joined Acme in 2019 as VP of Sales; she left in 2023."
    assert kept(JANE, page, "current_role", "VP of Sales", "Jane Doe joined Acme in 2019 as VP of Sales;") == []


def test_conjoined_other_person_role():
    page = "Jane Doe is VP of Sales and John Roe is CEO of Acme Inc."
    assert kept(JANE, page, "current_role", "CEO") == []


def test_while_other_person_role():
    page = "Jane Doe is VP of Sales at Acme Inc while John Roe is CEO."
    assert kept(JANE, page, "current_role", "CEO") == []


def test_common_word_company_lowercase_match():
    assert kept(Subject("company", "Square"), "The town square has 650 people.", "employee_count", "650") == []


def test_headcount_scoped_to_location():
    assert kept(ACME, "Acme Inc has 650 employees in Ohio.", "employee_count", "650") == []


def test_rumored_role():
    page = "Rumor says Jane Doe might become VP of Sales at Acme Inc."
    assert kept(JANE, page, "current_role", "VP of Sales") == []


def test_succeeded_by():
    page = "Jane Doe, VP of Sales at Acme Inc, is succeeded by John Roe as CEO."
    assert kept(JANE, page, "current_role", "CEO") == []


def test_hq_of_other_company_same_sentence():
    page = "Acme Inc is headquartered in Ohio, while Beta is headquartered in Texas."
    assert kept(ACME, page, "headquarters", "Texas") == []


def test_industry_of_competitor():
    page = "Acme Inc competes with Globex, a leader in aerospace."
    assert kept(ACME, page, "industry", "aerospace") == []


def test_news_about_other_company():
    page = "Globex acquired Initech, a former partner of Acme Inc."
    assert kept(ACME, page, "recent_news.x", "Globex acquired Initech") == []


def test_news_denial():
    assert kept(ACME, "Acme Inc denied rumors that it acquired Initech.", "recent_news.x", "acquired Initech") == []


def test_news_negation():
    assert kept(ACME, "Acme Inc did not acquire Initech.", "recent_news.x", "acquire Initech") == []


# ---- recall: obvious true facts dropped ------------------------------------

def test_recall_apostrophe_name():
    assert kept(Subject("person", "Sean O'Brien", "Acme Inc"), "Sean O'Brien is VP of Sales at Acme Inc.", "current_role", "VP of Sales")


def test_recall_hyphen_name():
    assert kept(Subject("person", "Jean-Luc Picard", "Acme Inc"), "Jean-Luc Picard is Captain at Acme Inc.", "current_role", "Captain")


def test_recall_us_abbreviation():
    assert kept(JANE, "Jane Doe is VP of Sales for U.S. operations at Acme Inc.", "current_role", "VP of Sales")


def test_recall_jr_abbreviation():
    assert kept(Subject("person", "John Smith", "Acme Inc"), "John Smith Jr. is VP of Sales at Acme Inc.", "current_role", "VP of Sales")


def test_recall_promoted():
    assert kept(JANE, "Jane Doe was promoted to VP of Sales at Acme Inc.", "current_role", "VP of Sales")


def test_recall_unicode_sentence_end():
    assert kept(JANE, "Jane Doe is VP of Sales at Acme Inc。Other text here。", "current_role", "VP of Sales", "Jane Doe is VP of Sales at Acme Inc。")

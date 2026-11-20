"""Total extraction LLM calls per briefing never exceed Budget.max_extraction_calls."""

import pytest

from cold_call_agents.extraction import SYSTEM_PROMPT
from cold_call_agents.orchestrator import run_research
from cold_call_agents.providers import MockProfiles, MockSearch
from cold_call_agents.researchers import Budget
from test_extraction import PROSPECT

PAGE = (
    "Northwind Logistics employs about 650 people across two plants. "
    "Dana Reyes, VP of Operations at Northwind Logistics, spoke at the Freight Summit."
)


class CountingLLM:
    """Always replies with invalid JSON, so every result burns a call plus a retry."""

    def __init__(self):
        self.extraction_calls = 0

    def complete(self, system, prompt):
        if system == SYSTEM_PROMPT:
            self.extraction_calls += 1
        return "not json"


def _search(n=6):
    return MockSearch([
        {"title": f"t{i}", "url": f"https://example.com/{i}", "content": PAGE, "publisher": "Example Wire",
         "published_date": "2026-09-01", "keywords": ["northwind", "dana"]}
        for i in range(n)
    ])


def _total(cap=None):
    llm = CountingLLM()
    budget = Budget() if cap is None else Budget(max_extraction_calls=cap)
    run_research(PROSPECT, llm=llm, search=_search(), profiles=MockProfiles(None, None), budget=budget)
    return llm.extraction_calls


@pytest.mark.parametrize("cap", [0, 1, 2, 3])
def test_total_never_exceeds_cap(cap):
    # Both researchers have plenty of results, so each would use more than its share.
    assert _total(cap) <= cap


def test_odd_and_even_caps_are_fully_used_when_both_want_more():
    assert _total(2) == 2
    assert _total(3) == 3


def test_default_cap_is_total_not_per_researcher():
    assert _total() == Budget().max_extraction_calls

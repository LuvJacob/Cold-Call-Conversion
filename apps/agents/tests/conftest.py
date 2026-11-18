from datetime import date

import pytest

from cold_call_agents.models import Prospect
from cold_call_agents.providers import FIXTURE_KEYS, load_fixture, mocks_from_fixture

TODAY = date(2026, 10, 22)


@pytest.fixture(params=FIXTURE_KEYS)
def key(request):
    return request.param


@pytest.fixture(autouse=True)
def _reset_edgar_cache():
    """Keep the EDGAR ticker cache from leaking between tests (hermetic)."""
    from cold_call_agents.free_sources import edgar

    edgar._tickers_cache = None
    yield
    edgar._tickers_cache = None


def setup(key):
    fx = load_fixture(key)
    llm, search, profiles = mocks_from_fixture(fx)
    return Prospect(**fx["prospect"]), llm, search, profiles

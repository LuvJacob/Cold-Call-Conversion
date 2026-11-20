"""Brief `mode` tells the UI whether a briefing is sample data or real research."""
from cold_call_agents.adapter import to_frontend_brief
from cold_call_agents.orchestrator import run_research
from cold_call_agents.models import Prospect
from cold_call_api.models import BriefModel


def _briefing():
    return run_research(Prospect(prospect_id="p1", name="Test Person", company="Test Co", role="CEO"))


def test_default_mode_is_demo():
    assert to_frontend_brief(_briefing())["mode"] == "demo"


def test_free_and_live_modes_pass_through_and_validate():
    for mode in ("free", "live"):
        d = to_frontend_brief(_briefing(), mode=mode)
        assert d["mode"] == mode
        assert BriefModel.model_validate(d).mode == mode


def test_unknown_mode_falls_back_to_demo():
    assert to_frontend_brief(_briefing(), mode="bogus")["mode"] == "demo"

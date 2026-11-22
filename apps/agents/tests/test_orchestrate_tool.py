"""The watsonx Orchestrate tool wraps the research pipeline and returns a cited briefing (offline, mocked)."""
import importlib.util
from pathlib import Path

from cold_call_agents.providers import load_fixture, mocks_from_fixture

TOOL = Path(__file__).resolve().parents[3] / "orchestrate" / "tools" / "cold_call_tools.py"


def _load():
    spec = importlib.util.spec_from_file_location("cold_call_tools", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_research_prospect_returns_cited_brief(monkeypatch):
    mod = _load()
    fx = load_fixture("northwind")
    monkeypatch.setattr(mod, "build_free_providers", lambda prospect, budget: mocks_from_fixture(fx))
    p = fx["prospect"]
    out = mod.research_prospect(p["name"], p["company"], p["role"])
    assert out["mode"] == "free"
    assert out["status"] in ("ready", "partial")
    assert out["facts"], "expected facts from the fixture"
    ids = {s["id"] for s in out["sources"]}
    assert all(f["sourceIds"] and set(f["sourceIds"]) <= ids for f in out["facts"])


def test_agent_yaml_references_the_tool():
    agent = (TOOL.parents[1] / "agents" / "cold_call_research_agent.yaml").read_text()
    assert "spec_version: v1" in agent and "kind: native" in agent
    assert "- research_prospect" in agent

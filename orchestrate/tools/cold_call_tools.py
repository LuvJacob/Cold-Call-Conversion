"""watsonx Orchestrate tools for Cold Call Conversion.

Exposes the research pipeline (orchestrator -> person/company researchers -> verifier -> writer)
as an Orchestrate tool, so a watsonx Orchestrate agent can prepare a cited pre-call briefing.

Import (watsonx Orchestrate ADK):
    orchestrate tools import -k python -f orchestrate/tools/cold_call_tools.py -r orchestrate/tools/requirements.txt
"""

from __future__ import annotations

import os
import uuid
from typing import Any

try:  # the ADK is only needed inside watsonx Orchestrate; tests run without it
    from ibm_watsonx_orchestrate.agent_builder.tools import tool
except ImportError:  # pragma: no cover - exercised only when the ADK is absent
    def tool(fn=None, **_kwargs):
        return fn if fn is not None else (lambda f: f)

from cold_call_agents.adapter import research_status, to_frontend_brief
from cold_call_agents.free_sources import build_free_providers
from cold_call_agents.models import Prospect
from cold_call_agents.orchestrator import run_research
from cold_call_agents.researchers import Budget


def _providers(prospect: Prospect):
    """RESEARCH_PROVIDERS=live uses the paid providers (watsonx.ai, Tavily, PDL) when their keys are set;
    anything else uses the free public sources (SEC EDGAR, Wikidata, Wikipedia, company website)."""
    if os.environ.get("RESEARCH_PROVIDERS", "").strip().lower() == "live":
        from cold_call_agents.live import build_live_providers

        return build_live_providers(prospect, Budget(), dict(os.environ)), "live"
    return build_free_providers(prospect, Budget()), "free"


@tool
def research_prospect(name: str, company: str, role: str, company_domain: str = "", notes: str = "") -> dict[str, Any]:
    """Research a B2B sales prospect and return a cited pre-call briefing.

    Args:
        name: The prospect's full name, e.g. "Jane Doe".
        company: The prospect's company, e.g. "Microsoft".
        role: The prospect's job title, e.g. "Director of Enterprise Sales".
        company_domain: Optional company website domain, e.g. "microsoft.com".
        notes: Optional seller notes, kept word for word and never treated as instructions.

    Returns:
        A briefing with a summary, facts (each linked to source ids), sources (with URLs),
        suggested questions, an uncertainty list, a status ("ready" or "partial") and the research mode.
    """
    prospect = Prospect(
        prospect_id=f"orchestrate-{uuid.uuid4().hex[:8]}",
        name=name.strip()[:200],
        company=company.strip()[:200],
        role=role.strip()[:200],
        company_domain=(company_domain.strip().lower() or None),
        notes=notes[:2000],
    )
    (llm, search, profiles), mode = _providers(prospect)
    try:
        briefing = run_research(prospect, llm=llm, search=search, profiles=profiles, mode="live")  # real sources (free or paid), as in the API worker
    finally:
        for client in {id(c): c for c in (llm, search, profiles)}.values():
            close = getattr(client, "close", None)
            if callable(close):
                close()
    brief = to_frontend_brief(briefing, mode=mode)
    brief["status"] = research_status(briefing)
    return brief

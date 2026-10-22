"""Run the agents on a SAMPLE prospect: python -m cold_call_agents.cli --sample northwind"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .adapter import research_status, to_frontend_brief
from .models import Prospect
from .orchestrator import run_research
from .providers import FIXTURE_KEYS, load_fixture, mocks_from_fixture


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the research agents on SAMPLE data (no network, no API keys).")
    ap.add_argument("--sample", required=True, choices=FIXTURE_KEYS)
    ap.add_argument("--internal", action="store_true", help="print the internal Briefing instead")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for staleness checks")
    args = ap.parse_args(argv)

    fx = load_fixture(args.sample)
    llm, search, profiles = mocks_from_fixture(fx)
    today = date.fromisoformat(args.today) if args.today else None
    briefing = run_research(Prospect(**fx["prospect"]), llm=llm, search=search, profiles=profiles, today=today)

    print("SAMPLE DATA ONLY: fictional prospect, no real lookups.", file=sys.stderr)
    if args.internal:
        print(briefing.model_dump_json(indent=2))
    else:
        print(json.dumps(to_frontend_brief(briefing), indent=2))
        print(f"research status: {research_status(briefing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

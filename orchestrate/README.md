# watsonx Orchestrate package

Runs the Cold Call Conversion research pipeline inside **IBM watsonx Orchestrate**.

| File | What it is |
|---|---|
| `tools/cold_call_tools.py` | `research_prospect` tool (ADK `@tool`): runs the orchestrator, person/company researchers, verifier and writer, and returns a cited briefing |
| `tools/requirements.txt` | Installs the `cold_call_agents` package from this repo |
| `agents/cold_call_research_agent.yaml` | Native Orchestrate agent (IBM Granite on watsonx) that calls the tool and presents the briefing with sources and uncertainty |

## Import into watsonx Orchestrate (ADK)

```bash
pip install ibm-watsonx-orchestrate
orchestrate env activate <your-environment>
orchestrate tools import -k python -f orchestrate/tools/cold_call_tools.py -r orchestrate/tools/requirements.txt
orchestrate agents import -f orchestrate/agents/cold_call_research_agent.yaml
```

Then open the agent in Orchestrate chat and ask, for example: *"Prepare me for a call with Ravien Solcrest, Director of Enterprise Sales at Microsoft (microsoft.com)."*

## Research mode

- Default: free public sources (SEC EDGAR, Wikidata, Wikipedia, company website). Set `SEC_USER_AGENT` (a descriptive name with a contact) so SEC lookups run.
- `RESEARCH_PROVIDERS=live`: also uses watsonx.ai (`WATSONX_API_KEY`, `WATSONX_URL`, `WATSONX_PROJECT_ID`), Tavily and People Data Labs when their keys are set. Missing keys fall back to the free sources.

Keys belong in Orchestrate connections or environment settings, never in this repo.

## Status

The tool is unit-tested offline (`apps/agents/tests/test_orchestrate_tool.py`) and was run locally against the free sources (Microsoft: 14 cited facts). The ADK file formats follow IBM's watsonx Orchestrate ADK documentation. The import has not yet been run in an Orchestrate instance; check flags against your ADK version.

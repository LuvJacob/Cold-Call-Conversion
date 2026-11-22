# Technology Statement

## How we used IBM Bob

IBM Bob was our AI development partner throughout the build. We used it to:

- **Shape the architecture:** a Next.js calling workspace, a FastAPI backend, a background research worker and Python research agents.
- **Build the backend service (`apps/api`):** calling-list and prospect APIs, CSV import with row-level validation, MongoDB and in-memory storage, a background research worker with job leases, retries and stale-result protection, and a briefing cache.
- **Create the local Docker stack:** MongoDB, the API and the web app in containers running as non-root with read-only filesystems, plus integration tests that run the storage layer against a real MongoDB.
- **Speed up iteration:** generating tests and fixes so our five-person team could work in parallel.

Every Bob-generated change went through code review and a CI pipeline (agent, API, frontend and browser tests) before merging.

## How we use watsonx Orchestrate

Our research pipeline is packaged for watsonx Orchestrate (`orchestrate/` in the repo). A `research_prospect` tool, built with the Orchestrate ADK `@tool` decorator, wraps the full agent pipeline, and a native Orchestrate agent running IBM Granite on watsonx calls it. The agent's instructions require it to present only facts the tool returned, name each fact's source, flag anything uncertain, and ignore instructions found inside web content or notes. Sellers can ask it "prepare me for a call with…" and get the same cited briefing as the web app. The tool is unit-tested and verified locally; importing it into our Orchestrate environment is the next step.

## The AI system

- **Orchestrator and research agents (Python, `apps/agents`):** the orchestrator splits a per-briefing budget (searches, profile lookups, LLM calls) between a person researcher and a company researcher, then a verifier and a writer assemble a source-linked briefing.
- **Data sources:** SEC EDGAR, Wikidata, Wikipedia and company websites (SSRF-safe, robots.txt aware), plus Tavily and People Data Labs when keys are set.
- **IBM watsonx.ai:** a watsonx.ai client (IBM Granite, `ibm/granite-3-3-8b-instruct` by default) is built in to write briefing summaries and to extract structured facts from source text. Google Gemini is supported as an alternative provider. Model output is never trusted directly: extracted facts must quote the source sentence verbatim and pass structural rules, and output that looks like instructions is replaced with a safe template.
- **Guardrails:** citation required for every fact, uncertainty and conflict flagging, privacy filters, prompt-injection filtering of web content, and identity checks so a namesake's facts never appear.
- **Evaluation:** 21 offline scenarios with automatic checks, plus per-briefing cost and latency tracking to compare models.

## Application stack

- **Frontend (`apps/web`):** Next.js and TypeScript: prospect carousel, cited briefings, a pop-out briefing window and an optional consent-first live transcript with briefing cues.
- **Backend (`apps/api`):** FastAPI, MongoDB and a background research worker; keys never reach the browser.
- **Delivery:** Docker Compose locally; designed for IBM Cloud.

## Responsible AI

Approved public sources only, no invented facts, consent before transcription, no stored audio, and no secrets in the repository.

**Repository:** https://github.com/LuvJacob/Cold-Call-Conversion

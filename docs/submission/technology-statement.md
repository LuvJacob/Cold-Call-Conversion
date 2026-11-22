# Technology Statement

## How we used IBM Bob

IBM Bob was our AI development partner throughout the build. We used it to:

- **Shape the architecture:** a Next.js calling workspace, a FastAPI backend, a background research worker and Python research agents.
- **Build the backend service (`apps/api`):** calling-list and prospect APIs, CSV import with row-level validation, MongoDB and in-memory storage, a background research worker with job leases, retries and stale-result protection, and a briefing cache.
- **Create the local Docker stack:** MongoDB, the API and the web app in containers running as non-root with read-only filesystems, plus integration tests that run the storage layer against a real MongoDB.
- **Speed up iteration:** generating tests, suggesting fixes and explaining code across lanes, so a five-person team could work in parallel on agents, backend, frontend and product.

Every Bob-generated change went through code review and automated tests before merging. A GitHub Actions pipeline runs the agent, API, frontend and end-to-end browser tests on every pull request.

## The AI system

- **Orchestrator and research agents (Python, `apps/agents`):** the orchestrator splits a per-briefing budget (searches, profile lookups, LLM calls) between a person researcher and a company researcher, then a verifier and a writer assemble a source-linked briefing.
- **Data sources:** SEC EDGAR, Wikidata, Wikipedia and the company homepage, fetched with SSRF protection, robots.txt checks, retries and rate-limit handling. Tavily search and People Data Labs enrichment are integrated and switch on when keys are provided. Missing keys fall back to free sources.
- **IBM watsonx.ai:** a watsonx.ai client (IBM Granite, `ibm/granite-3-3-8b-instruct` by default) is built in to write briefing summaries and to extract structured facts from source text. Google Gemini is supported as an alternative provider. Model output is never trusted directly: extracted facts must quote the source sentence verbatim and pass structural rules, and output that looks like instructions is replaced with a safe template.
- **Guardrails:** citation required for every fact, uncertainty and conflict flagging, privacy filters, prompt-injection filtering of web content, and identity checks so a namesake's facts never appear.
- **Evaluation:** 21 offline scenarios with automatic checks, plus cost and latency tracking per briefing, so models such as watsonx and Gemini can be compared on quality and cost.

## Application stack

- **Frontend (`apps/web`):** Next.js, React and TypeScript, with a prospect carousel, cited briefing view, pop-out briefing window (Document Picture-in-Picture) and an optional consent-first live transcript with briefing cues (Web Speech API).
- **Backend (`apps/api`):** FastAPI with Pydantic validation, MongoDB, a background research worker with retries, and a server-side proxy so no keys or credentials ever reach the browser.
- **Delivery:** Docker Compose for local runs; designed to deploy on IBM Cloud with a managed MongoDB-compatible database.

## Responsible AI

The system uses only approved public sources, never invents facts, labels sample data clearly, transcribes only with consent, and stores no audio. Keys stay server-side, and the public repository contains no secrets.

**Repository:** https://github.com/LuvJacob/Cold-Call-Conversion

# Cold Call Conversion

An agentic AI sales assistant that researches prospects before the call, so B2B sellers know who they're calling before the conversation begins.

## Hackathon submission (IBM SkillsBuild AI Experiential Learning Lab)

- **Demo video (2 min):** YouTube link to be added
- **Problem and solution statement:** [docs/submission/problem-and-solution.md](docs/submission/problem-and-solution.md)
- **Technology statement (IBM Bob):** [docs/submission/technology-statement.md](docs/submission/technology-statement.md)
- **Run the demo yourself:** [docs/demo-runbook.md](docs/demo-runbook.md)

## Project status

A browser-local frontend demo is available in `apps/web`. Product scope, team roles, and the challenge submission are defined. A rough low-fidelity MVP exists in a **separate repository**: [Cold-Call-Conversion-rx](https://github.com/LuvJacob/Cold-Call-Conversion-rx), which is used to demonstrate the core concept and guide the build here.

Next up: agree on the agent input/output format and API contracts, build the backend and agent services, and connect the frontend demo.

Frontend setup: [apps/web/README.md](apps/web/README.md). Backend setup: [apps/api/README.md](apps/api/README.md). Agent setup: [apps/agents/README.md](apps/agents/README.md). Backend integration handoff: [docs/frontend-integration.md](docs/frontend-integration.md).

## How it works

1. **Add prospects:** the seller uploads or enters a calling list with names, titles, companies, and notes.
2. **Research:** an orchestrator agent assigns research tasks to specialized sub-agents, which pull data through search and data APIs (such as Tavily and People Data Labs) and free public sources.
3. **Verify and save:** agents cross-check findings, flag uncertainty, and cache briefings so the same prospect isn't researched twice.
4. **Call ready:** the seller works through a prospect carousel. When a call connects, the briefing is already on screen.

## MVP scope

| In the MVP | Not in the MVP |
|---|---|
| Prospect entry | Call recording (no audio is ever saved) |
| Pre-call enrichment | AI conversation analysis (planned with IBM speech services) |
| Briefings that link their sources | |
| Manual call-status controls | |
| Live call transcript (optional, consent first) with keyword cues from the briefing | |

**Live transcript:** added to the MVP at the team lead's request. During a call the on-call view can transcribe the conversation with the browser's speech service (Chrome or Edge). It is off by default and needs a consent tick. No audio or transcript goes to our backend or storage. Keyword cues (pricing, timeline, competitor...) point to related questions and facts from the briefing; there is no AI analysis of the call yet.

**Success measures:** preparation time, briefing usefulness, source coverage.

## Planned architecture

- **Runtime AI:** an IBM Cloud enterprise model for research reasoning and summarization; exact service and model remain open.
- **Research data (v1.0):** API calls, not web scraping: Tavily for web search and news, People Data Labs for person and company profiles, plus free public sources (SEC EDGAR, Wikipedia). See [docs/agent-design.md](docs/agent-design.md).
- **Cloud:** connecting to IBM tools such as IBM Cloud *(details TBD)*.
- **Agents:** an orchestrator plus research sub-agents, with cross-source verification and guardrails.
- **Backend:** APIs, research services, and NoSQL storage for seller cadence data. Exact database and backend stack remain open.
- **Frontend:** Next.js, React, and TypeScript calling workspace with a prospect queue, briefing view, and manual call controls. The current demo uses local sample data.
- **Dev partner:** IBM Bob helps with architecture, backend tools, orchestration, frontend integration, testing, and deployment.

## Work lanes

Each person owns one lane. Build only inside your lane; if you need something changed in another lane, ask that lane's owner.

| Lane | Owner | Role |
|---|---|---|
| A: Integration and MVP | **Jacob Webb** (@LuvJacob) | Project Manager, Team Lead & MVP Prototyping |
| B: AI agents | **James Afon** | AI Engineer & Agent Optimization Lead |
| C: Backend | **Srikar Satluri** | Lead Backend & Systems Architecture Engineer |
| D: Frontend | **Aanand Suryavanshi** | Lead Frontend & AI Experience Engineer |
| E: Product and research | **Joseph Ross** | Product Manager & User Research Lead |

### Lane A: Integration and MVP (Jacob)

- **Does:** runs the timeline and task assignments; owns this repo and reviews and merges PRs (unless he has said otherwise, see Team workflow); maintains the low-fi MVP; makes the system diagrams and architecture docs; leads the final demo and presentation.
- **First deliverable:** architecture diagram tied to the [MVP repo](https://github.com/LuvJacob/Cold-Call-Conversion-rx), so every lane builds toward the same picture.
- **Does not:** write lane features. Jacob decides scope and settles overlaps between lanes.

### Lane B: AI agents (James)

- **Does:** picks the models, frameworks, MCPs, and tools; manages API keys; designs the orchestrator and research sub-agents (what each searches, when it stops, how it resolves conflicting info); builds guardrails for accuracy, privacy, and responsible use; tunes latency, token use, and cost.
- **First deliverable:** one prospect in, one source-linked briefing out (runnable on its own), plus the agreed briefing format.
- **Does not:** build backend APIs, the database, or UI. James hands Srikar a clear agent interface to call.

### Lane C: Backend (Srikar)

- **Does:** designs the backend architecture and APIs; handles calling-list upload and processing; stores and caches briefings; calls the agent service from Lane B; keeps the system secure, reliable, and fast.
- **First deliverable:** API that accepts a calling list and returns stored briefings (using a sample briefing until the agents are wired in).
- **Does not:** write agent prompts or logic, or build UI. Srikar publishes the API contract Aanand builds against.

### Lane D: Frontend (Aanand)

- **Does:** builds the UI: calling list entry, prospect carousel, briefing view when a call connects, manual call-status controls, and "next lead"; connects the UI to Lane C's APIs; tests and improves usability.
- **First deliverable:** clickable calling flow using sample briefings: add a list, move through prospects, open a briefing, mark call status.
- **Does not:** call the LLM or agents directly. All data comes through the backend.

### Lane E: Product and research (Joseph)

- **Does:** interviews SDRs/BDRs about cold-calling pain points; turns findings into requirements, user stories, and priorities; studies comparable products and demos; keeps meeting notes and progress updates; runs user testing on the MVP.
- **First deliverable:** a ranked list of what sellers want in a briefing. This decides which fields Lane B researches and Lane D displays.
- **Does not:** write code. Joseph's findings set priorities for the other lanes.

### How the lanes connect

```
Joseph (what sellers need)
      |
      v
James (agents produce briefings) --> Srikar (backend stores & serves them) --> Aanand (UI shows them)
      \_____________________________________|_____________________________________/
                                            v
                              Jacob (reviews, merges, demos)
```

- **B to C:** James and Srikar agree on the briefing format and how the backend calls the agents.
- **C to D:** Srikar and Aanand agree on the API contract before building against it.
- **E to everyone:** Joseph's findings decide which briefing fields matter most.
- **Everyone to A:** all work merges through Jacob, unless he has said otherwise.

## Team workflow

- Branch from the latest `main`, one branch per feature, named after your lane (e.g. `agents/briefing-format`, `frontend/carousel`).
- Open small PRs that say what changed, how you tested it, and what it depends on.
- Jacob approves merges unless he has said otherwise. When Jacob agrees, a lane owner may merge their own PRs without his review. Keep `main` runnable.
- Changes to shared interfaces (briefing format, API contracts) are agreed between the affected owners before anyone edits them.
- Use sample data until real connections are ready, and label it clearly as sample data.

## Continuous integration

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every pull request and every push to `main`. It needs no secrets. Jobs:

- `agents`: `pytest` for `apps/agents` (Python 3.12).
- `api`: `pytest` for `apps/api` (Python 3.12, agents package installed first).
- `web`: `npm ci`, typecheck, unit tests, and `next build` in `apps/web` (Node 22).
- `web-e2e`: Playwright end-to-end tests against the local Next dev server (Chromium).

PRs should be green before merging. Superseded runs on the same branch are cancelled automatically.

## Run locally with Docker

One command starts MongoDB, the API (on the Mongo storage) and the web app. You need Docker with Compose v2 (Docker Desktop, or `brew install docker docker-compose colima && colima start`).

```sh
cp .env.example .env        # then set MONGO_ROOT_PASSWORD to a long random value
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Web | http://127.0.0.1:3000 | Next.js app |
| API | http://127.0.0.1:8000 (docs at `/docs`) | `ENVIRONMENT=development`, `AUTH_MODE=dev`, `STORAGE_BACKEND=mongodb` |
| MongoDB | `127.0.0.1:27017` | Root user from `.env`; data kept in the `mongo-data` volume |

Stop with `docker compose down`; add `-v` to also delete the database volume.

- Host ports are published on `127.0.0.1` only, and each container binds to a fixed address on a private network, never `0.0.0.0`.
- Containers run as non-root with a read-only root filesystem and all capabilities dropped. Base images are Red Hat UBI (`registry.access.redhat.com`) and the official MongoDB UBI image.
- The web app is still the browser-local sample-data demo; it does not call the API yet.
- This is **local development only**: `AUTH_MODE=dev` trusts the `X-Seller-ID` header and Mongo traffic is not TLS-encrypted. For anything deployed use `AUTH_MODE=jwt`, `ENVIRONMENT=production` and a TLS Mongo connection (see [apps/api/README.md](apps/api/README.md)).
- **Research modes** (`RESEARCH_PROVIDERS` in `.env`, default `free`):
  - `free`: real public lookups (Wikidata, SEC EDGAR, company website) for prospects that are not the built-in samples. This makes real network calls from the API container but needs no API keys. Set `SEC_USER_AGENT` (descriptive text with a contact, as SEC requires; unset skips EDGAR) and optionally `RESEARCH_CONTACT` to your own details.
  - `live`: paid providers (LLM, search, profiles). Keys go in `.env` (never committed); missing keys fall back to free sources. See [apps/agents/README.md](apps/agents/README.md) for the key names. Compose passes these keys to the `api` service.
  - empty (`RESEARCH_PROVIDERS=` set to nothing in `.env`): offline sample fixtures only, no network calls.
- `.env` is git-ignored. Never commit it, and never put real keys in `.env.example`.

## Local development

Use Node.js 22.13 or newer.

```sh
cd apps/web
npm ci
npm run dev
```

Open http://localhost:3000. See [frontend setup and verification](apps/web/README.md) for tests and demo limits. No model or database credentials are needed for this frontend demo.

## Rules

- Never commit API keys, `.env` files, or credentials. Keys stay server-side (the backend and the research worker), never in the frontend.
- Use only permitted or authorized data sources for prospect research.
- Briefings must cite their sources and flag uncertain or conflicting info.

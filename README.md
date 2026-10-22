# Cold Call Conversion

An agentic AI sales assistant that researches prospects before the call, so B2B sellers know who they're calling before the conversation begins.

## Project status

This repository is new. Product scope, team roles, and the challenge submission are defined. A rough low-fidelity MVP exists in a **separate repository**: [Cold-Call-Conversion-rx](https://github.com/LuvJacob/Cold-Call-Conversion-rx), which is used to demonstrate the core concept and guide the build here.

Next up: agree on the agent input/output format and API contracts, then start the backend, agent, and frontend lanes in parallel.

Planned docs (coming soon): product requirements, architecture diagram, setup guide.

## How it works

1. **Add prospects:** the seller uploads or enters a calling list with names, titles, companies, and notes.
2. **Research:** an orchestrator agent assigns research tasks to specialized sub-agents (public websites, search engines, authorized professional-data sources).
3. **Verify and save:** agents cross-check findings, flag uncertainty, and cache briefings so the same prospect isn't researched twice.
4. **Call ready:** the seller works through a prospect carousel. When a call connects, the briefing is already on screen.

## MVP scope

| In the MVP | Not in the MVP |
|---|---|
| Prospect entry | Live transcription |
| Pre-call enrichment | Call recording |
| Briefings that link their sources | Automatic conversation analysis |
| Manual call-status controls | |

**Success measures:** preparation time, briefing usefulness, source coverage.

## Planned architecture

- **Runtime AI:** Gemini API for research reasoning and summarization.
- **Agents:** an orchestrator plus research sub-agents, with cross-source verification and guardrails.
- **Backend:** APIs, research services, and briefing storage/cache. *(stack TBD)*
- **Frontend:** calling workflow UI with a prospect carousel and briefing view. *(stack TBD)*
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

- **Does:** runs the timeline and task assignments; owns this repo, reviews and merges every PR; maintains the low-fi MVP; makes the system diagrams and architecture docs; leads the final demo and presentation.
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
- **Does not:** call Gemini or agents directly. All data comes through the backend.

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
- **Everyone to A:** all work merges through Jacob.

## Team workflow

- Branch from the latest `main`, one branch per feature, named after your lane (e.g. `agents/briefing-format`, `frontend/carousel`).
- Open small PRs that say what changed, how you tested it, and what it depends on.
- Jacob approves merges. Keep `main` runnable.
- Changes to shared interfaces (briefing format, API contracts) are agreed between the affected owners before anyone edits them.
- Use sample data until real connections are ready, and label it clearly as sample data.

## Local development

*Setup instructions will be added once the stack is chosen.*

## Rules

- Never commit API keys, `.env` files, or credentials. Keys stay on the backend.
- Use only permitted or authorized data sources for prospect research.
- Briefings must cite their sources and flag uncertain or conflicting info.

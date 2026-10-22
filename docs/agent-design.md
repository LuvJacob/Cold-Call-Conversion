# Agent Design (Lane B)

**Owner:** James Afon (Lane B: AI agents)
**Status:** Draft for team review
**Needs sign-off from:** Srikar (agent interface and briefing format), Joseph (which briefing fields matter), Jacob (scope)
**FYI:** Aanand (Lane D displays the briefing, including source links and certainty labels)

## Purpose

The agents research one prospect before a call and return a short briefing with a source on every claim. They do not place calls, record calls, or analyze conversations. The seller makes the call; the agents make sure the seller is prepared.

These are the runtime agents inside the product (running on Gemini). They are separate from the `builder`, `reviewer`, and `tester` agents in `.claude/agents/`, which only help us write code.

> **Note:** the briefing format and the backend interface in this doc are **proposals**. Nothing is built against them until Srikar (and Joseph, for the fields) agree.

## Overview

MVP: 1 orchestrator + 4 sub-agents.

```
Backend (Lane C) sends one prospect
          |
          v
   +--------------+
   | Orchestrator |  plans the research, enforces limits
   +--------------+
      |        |
      v        v              (run in parallel)
 +----------+ +----------+
 |  Person  | | Company  |
 | research | | research |
 +----------+ +----------+
       \        /
        v      v
   +-----------+
   | Verifier  |  cross-checks, flags conflicts and stale facts, drops unsourced claims
   +-----------+
         |
         v
   +-----------------+
   | Briefing writer |  produces the briefing in the proposed format
   +-----------------+
         |
         v
Backend stores and caches it; frontend (Lane D) shows it
```

## The agents

| Agent | Input | Output | Stops when |
|---|---|---|---|
| **Orchestrator** | Prospect: name, title, company, optional notes, optional seller offering | Final briefing, or a partial briefing with reasons | Both researchers return, or the time/cost limit is hit |
| **Person researcher** | Name, title, company | Identity match result, plus facts about the person, each with sources | It has covered the person fields in the proposed format, or hits its search limit |
| **Company researcher** | Company name (plus domain if known) | Company facts and recent news, each with sources | It has covered the company fields in the proposed format, or hits its search limit |
| **Verifier** | All facts from both researchers | Each fact given a status and a stale flag; unsourced facts removed | Every fact is checked |
| **Briefing writer** | Verified facts, optional seller offering | Briefing in the proposed format, including talking points | One pass (no loops) |

### Orchestrator

- Starts as plain code, not an AI model. The steps are fixed for the MVP, so this saves cost and keeps behavior predictable. We can add model-based planning later if prospects need different research paths.
- Runs the two researchers in parallel.
- Enforces limits on time, number of searches, and tokens per prospect.
- If a researcher fails or times out, it still returns a partial briefing that lists what is missing, rather than failing the whole request.

### Person researcher

- Looks for: current role and how long they've held it, past roles, public posts/talks/articles, and shared context the seller could mention.
- Uses only public websites, search engines, and authorized professional-data sources (per the README rules).
- Must confirm it found the right person (name + company match) before collecting facts. It reports the result as `identity_match`: `confirmed`, `likely`, or `unsure`. If `unsure`, it does not collect person facts, and the briefing says so.

### Company researcher

- Looks for: what the company does, size, industry, and recent news (funding, hiring, launches, leadership changes).
- Recent news is the main source of talking points, so it should prefer recent, dated sources.

### Verifier

- Compares facts across sources and gives each fact a `status`:
  - Two or more independent sources agree: `confirmed`.
  - One source only: `single-source` (kept, but shown as less certain).
  - Sources disagree: `conflicting`. Keep both versions with their sources so the seller can see the disagreement. Show the version from the more recent source first.
  - No source: removed.
- Separately marks a fact `stale: true` when its newest source is older than a cutoff (proposed: 12 months for roles and company size; news is judged by its own date).
- Sources with no date are allowed (`date: null`). They count toward `confirmed` but can't win a recency tie-break, and a fact backed only by undated sources is treated as possibly stale.

### Briefing writer

- Turns verified facts into the proposed briefing format.
- Every fact links to its source. It adds no new facts at this step.
- Writes **talking points**: short suggestions for opening the call, each one built only from verified facts and linked to them. If the seller's offering is provided, it uses it to pick relevant points; if not, the talking points stay general.
- Keeps the briefing short enough to read in the seconds before a call connects.

## Guardrails

- **Accuracy:** no claim without a source; uncertain, conflicting, and stale info is labeled, not hidden.
- **Identity:** if we can't confirm we found the right person, the briefing says so and leaves out person facts.
- **Privacy:** professional information only. No home addresses, personal phone numbers, family details, or other sensitive personal data, even if found.
- **Allowed sources only:** public pages, search engines, and authorized data providers. No scraping behind logins or against a site's terms.
- **Untrusted web content:** text from fetched pages is treated as data, never as instructions to the agents. Agents have no tools beyond search and page fetch, so a malicious page can't make them take other actions.
- **Data handling:** send Gemini and the search API only what each step needs. Don't log prospect details beyond what's needed to debug, and don't keep raw page dumps.
- **Keys:** Gemini and search API keys are read from environment variables (`.env` locally) by whichever process runs the agents. They are never committed to the repo and never sent to the frontend.

## Cost and speed

- Cache briefings (Lane C stores them) so the same prospect isn't researched twice.
- Use a fast, cheaper Gemini model for research and verification. Use a stronger one only where quality clearly improves (likely the briefing writer). Exact models are TBD after testing.
- Per-prospect limits on searches and tokens, set by the orchestrator.
- **Proposed starting budget** so Srikar can set timeouts: about 60 seconds per prospect for the whole pipeline. We'll adjust it after measuring.
- We'll measure against the README success measures: preparation time, briefing usefulness, and source coverage (share of briefing fields filled with a sourced fact), plus cost per briefing.
- In development and tests, use mocked search results to keep paid API calls low. Mocked data is clearly labeled as sample data.

## Proposed interface with the backend (needs Srikar's agreement)

This is a starting proposal only.

- The backend calls the agent service once per prospect.
- **Input:** `name`, `title`, `company`, optional `company_domain`, optional `notes`, optional `seller_offering` (a short description of what the seller sells).
- **Output:** a briefing object containing:
  - `prospect`: the input echoed back
  - `identity_match`: `confirmed` / `likely` / `unsure`
  - `sections`: person and company sections, each a list of facts
  - each fact: `id`, `text`, `sources` (each a URL plus `date`, which may be null), `status` (`confirmed` / `single-source` / `conflicting`), `stale` (true/false)
  - `talking_points`: each with `text` and the `fact_ids` it's based on
  - `missing`: what couldn't be found and why
  - `generated_at`

The exact fields depend on Joseph's ranked list of what sellers want.

## Build order

1. **Agree the briefing format and interface** with Srikar and Joseph.
2. **One prospect in, one briefing out**, runnable on its own with mocked search (the Lane B first deliverable).
3. Swap in real search for a small set of test prospects and measure time, cost, source coverage, and briefing usefulness.
4. Hand Srikar a stable interface to call.

## Later (not MVP)

- **Objection-prep agent:** likely objections and responses, tailored to what the seller sells.
- **Trigger-events agent:** watches saved prospects for new news (funding, job changes).
- **Model-based orchestrator:** chooses different research paths per prospect.

Whether we build these depends on Joseph's seller interviews.

## Open questions

1. Which briefing fields matter most to sellers? (Joseph)
2. Will the backend call the agents per prospect or per batch, and how long can it wait? (Srikar)
3. Do the agents run as a separate service the backend calls over HTTP, or as a library inside the backend? This decides where the Gemini and search keys live. (Srikar, James)
4. Which authorized professional-data sources can we use, and who holds the access? (Jacob, James)
5. Which search API will we use, and what budget do we have for it? (James, Jacob)
6. How long should a cached briefing stay valid before it's refreshed? (Srikar, James)
7. Should the seller's offering be entered once per calling list or per prospect? (Joseph, Aanand)

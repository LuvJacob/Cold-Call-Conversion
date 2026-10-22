# Agent Design (Lane B)

**Owner:** James Afon (Lane B: AI agents)
**Status:** Draft for team review
**Needs sign-off from:** Srikar (agent interface and briefing format), Joseph (which briefing fields matter), Jacob (scope)
**FYI:** Aanand (Lane D displays the briefing, including source links and certainty labels)

## Purpose

The agents research one prospect before a call and return a short briefing with a source on every claim. They do not place calls, record calls, or analyze conversations. The seller makes the call; the agents make sure the seller is prepared.

These are the runtime agents inside the product (running on an LLM: Gemini or IBM watsonx.ai, TBD). They are separate from the `builder`, `reviewer`, and `tester` agents in `.claude/agents/`, which only help us write code.

> **Note:** the briefing format and the backend interface in this doc are **proposals**. Nothing is built against them until Srikar (and Joseph, for the fields) agree.

## Where the agents run

This follows Aanand's system architecture diagram:

```
Seller -> Next.js calling workspace (Supabase Auth) <-> FastAPI backend -> PostgreSQL
                                                             |
                                                             v
                                                       Research queue
                                                             |
                                                             v
                                                  Python research worker   -> PostgreSQL
                                                             |
                                                             v
                                           Research and verification agents
                                                  |                  |
                                                  v                  v
                                             Gemini API   Approved search and
                                                          information sources
```

- The agents are **Python** code that runs inside the **research worker**. Lane B owns the agents; the worker process and queue setup are shared with Lane C (see open questions).
- The FastAPI backend doesn't call the agents directly. It puts one research job per prospect on the **research queue**. The worker picks up the job, runs the agents, and saves the briefing to **PostgreSQL**.
- The frontend never talks to the agents or the LLM. It reads briefings through the backend.

## The agents

MVP: 1 orchestrator + 4 sub-agents.

```
Research worker picks up one prospect job
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
Worker saves it to PostgreSQL; backend serves it; frontend (Lane D) shows it
```

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
- Uses only two of the sources listed in Data sources (per the README rules): People Data Labs for the profile, and Tavily for public talks, posts, and articles.
- Must confirm it found the right person (name + company match) before collecting facts. It reports the result as `identity_match`: `confirmed`, `likely`, or `unsure`. If `unsure`, it does not collect person facts, and the briefing says so.

### Company researcher

- Looks for: what the company does, size, industry, and recent news (funding, hiring, launches, leadership changes).
- Recent news is the main source of talking points, so it should prefer recent, dated sources.
- Sources: People Data Labs company data, the company's own homepage and About page, Wikipedia/Wikidata, SEC EDGAR (US public companies), and Tavily for recent news.

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

## Data sources (v1.0)

**Decision (James, Oct 22 2026):** v1.0 gets its data from **APIs, not a web-scraping agent.** Scraping runs into bot blockers, captchas, and site terms of service, which would make it slow to build and easy to break. Every source below is a plain API call with a key (or no key) and returns structured data.

| Need | Source | Free tier (checked Oct 2026, confirm on vendor site) | Used by |
|---|---|---|---|
| Web search, news, page text | **Tavily** (chosen search API) | ~1,000 credits/month, no card; basic search = 1 credit | Person + company researchers |
| Person and company profiles | **People Data Labs** | ~100 lookups/month, no card; no emails/phones on free tier | Person + company researchers |
| Public company filings | **SEC EDGAR** | Free, no key | Company researcher |
| Company background | **Wikipedia / Wikidata** | Free, no key | Company researcher |
| Company's own site | Direct fetch of homepage / About page (1-2 pages, no crawling) | Free | Company researcher |

**Considered and not used for v1.0:**
- **Apollo:** free plan doesn't appear to include API access (paid starts around $49/user/month). Revisit if the team pays for it.
- **Google Custom Search API:** closed to new customers; shuts down Jan 1, 2027.
- **Brave Search API:** free plan removed Feb 2026; now needs a card.
- **Hunter.io:** 50 credits/month with API; email-finding isn't needed for briefings. Optional later.
- **Scraping LinkedIn or any site behind a login:** against terms. Not allowed.

**Budget note:** about 100 People Data Labs lookups a month covers roughly 50 test prospects (person + company). That's enough for development and QA, not for real use, so the briefing cache matters. If we outgrow free tiers, the team decides on paid plans.

**To check:** Gemini and watsonx.ai may offer built-in web search ("grounding") that could replace some Tavily calls. Part of the LLM comparison.

## Guardrails

- **Accuracy:** no claim without a source; uncertain, conflicting, and stale info is labeled, not hidden.
- **Identity:** if we can't confirm we found the right person, the briefing says so and leaves out person facts.
- **Privacy:** professional information only. No home addresses, personal phone numbers, family details, or other sensitive personal data, even if found.
- **Allowed sources only:** the APIs listed in Data sources, plus direct fetches of a company's own public pages. No scraping behind logins or against a site's terms, no LinkedIn scraping, and no getting around captchas or bot blockers. If a page blocks us, we skip it.
- **Untrusted web content:** text from fetched pages is treated as data, never as instructions to the agents. Agents have no tools beyond the data-source APIs listed above and page fetch, so a malicious page can't make them take other actions. Direct page fetches are the riskiest input, so they are limited to the company's own domain, capped in size, and stripped to plain text before the LLM sees them.
- **Data handling:** send the LLM and each data API only what each step needs. Don't log prospect details beyond what's needed to debug, and don't keep raw page dumps.
- **Keys:** LLM, Tavily, and People Data Labs keys live only in the research worker's environment variables (`.env` locally). The backend and frontend never need them. They are never committed to the repo.

## Cost and speed

- Cache briefings in PostgreSQL so the same prospect isn't researched twice. Before queuing a job, the backend checks for a fresh briefing; the worker checks again before spending API calls.
- Use a fast, cheaper model for research and verification. Use a stronger one only where quality clearly improves (likely the briefing writer). Exact models are TBD after testing.
- Per-prospect limits on searches and tokens, set by the orchestrator.
- **Proposed starting budget** so Srikar can set the job timeout: about 60 seconds per prospect for the whole pipeline. We'll adjust it after measuring. Because research runs from a queue, the seller doesn't wait on it live; the goal is that briefings are ready before the seller reaches that prospect in the carousel.
- We'll measure against the README success measures: preparation time, briefing usefulness, and source coverage (share of briefing fields filled with a sourced fact), plus cost per briefing.
- In development and tests, use mocked search results to keep paid API calls low. Mocked data is clearly labeled as sample data.

## Quality checks (QA)

QA is not another agent in the product. It's a test setup built alongside the agents and run on every change (by the `tester` agent) before anything merges.

- **Test set:** 10-20 sample prospects, mostly public people at public companies, so we know the right answers. Includes hard cases: common names, small private companies, someone who recently changed jobs.
- **Automatic checks on every briefing:**
  - every fact has at least one source URL, and the URLs work
  - the right person was identified (`identity_match` matches the expected answer)
  - no private data (home address, personal phone, family details)
  - output matches the briefing format
  - time and API credits stayed under budget
- **Quality scoring:** an LLM grades each briefing for usefulness and accuracy against its sources; Joseph spot-checks a sample by hand.
- **Mocks by default:** everyday tests use saved API responses, so QA doesn't spend free credits. A small live run on a few prospects happens before releases.

## Proposed interface with the backend (needs Srikar's agreement)

This is a starting proposal only. The handoff happens through the research queue and PostgreSQL, not a direct API call.

- **Job (backend puts on the queue):** one per prospect: `prospect_id`, `name`, `title`, `company`, optional `company_domain`, optional `notes`, optional `seller_offering` (a short description of what the seller sells).
- **Job status (worker updates):** `queued` -> `running` -> `done` / `partial` / `failed`, so the UI can show "researching..." on a prospect card.
- **Result (worker saves to PostgreSQL):** a briefing object linked to `prospect_id`. Srikar owns the table design; the briefing itself can be stored as one JSON column so the format can change without a database migration. It contains:
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
4. Connect the agents to the research worker and queue with Srikar.

## Later (not MVP)

- **Objection-prep agent:** likely objections and responses, tailored to what the seller sells.
- **Trigger-events agent:** watches saved prospects for new news (funding, job changes).
- **Model-based orchestrator:** chooses different research paths per prospect.

Whether we build these depends on Joseph's seller interviews.

## Open questions

1. Which briefing fields matter most to sellers? (Joseph)
2. Which queue do we use (for example Redis-based, or a Postgres-backed job table), and who sets up and owns the worker process? (Srikar, James)
3. Who writes the briefing to PostgreSQL: the worker directly (as in the diagram), or the worker hands it back to the backend to save? (Srikar)
4. How are failed jobs retried, and how many times? (Srikar, James)
5. Do People Data Labs' and Tavily's terms allow our use, and who holds the team accounts and keys? (Jacob, James)
6. Search API is decided (Tavily). Which LLM do we use: Gemini or IBM watsonx.ai? And what budget do we have if we outgrow the free tiers (Tavily, People Data Labs), or want Apollo? (James, Jacob)
7. How long should a cached briefing stay valid before it's refreshed? (Srikar, James)
8. Should the seller's offering be entered once per calling list or per prospect? (Joseph, Aanand)

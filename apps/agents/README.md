# Cold Call Conversion: research agents (Lane B, v0)

Python package `cold_call_agents`. It researches one prospect before a call and produces a briefing with a source on every claim. Design: [`docs/agent-design.md`](../../docs/agent-design.md).

**Everything here runs on fictional SAMPLE data.** The three prospects in `cold_call_agents/fixtures/` are made up. By default there are no network calls, no API keys, and no `.env`. The optional free sources below make real network calls, but still need no API keys.

## Setup

```sh
cd apps/agents
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Run the tests

```sh
.venv/bin/pytest -q
```

## Run the CLI (one command per sample)

```sh
.venv/bin/python -m cold_call_agents.cli --sample northwind    # clean case, two sources agree
.venv/bin/python -m cold_call_agents.cli --sample harborview   # conflict, stale/undated source, private data, injection text
.venv/bin/python -m cold_call_agents.cli --sample cedarridge   # identity unsure, no person facts
```

Stdout is the frontend-shaped brief JSON. A "SAMPLE DATA ONLY" notice and the research status go to stderr. Options: `--internal` prints the internal briefing instead; `--today YYYY-MM-DD` fixes the date used for staleness checks.

## Module map

- `models.py`: pydantic models (Prospect, Source, Fact, TalkingPoint, Briefing, ResearchStatus).
- `providers.py`: provider Protocols (LLM, search, profiles) plus SAMPLE-data mocks and fixture loading.
- `researchers.py`: person researcher (with identity check) and company researcher; deterministic extraction in v0.
- `guardrails.py`: drops private data, sanitizes web text (treated as data, never instructions), requires a source on every fact.
- `verifier.py`: marks facts confirmed / single-source / conflicting, sets stale flags, orders conflicts most recent first.
- `writer.py`: builds the briefing (summary, talking points) through the LLM client; adds no new facts.
- `adapter.py`: converts the internal briefing to the frontend `briefSchema` shape and computes research status.
- `orchestrator.py`: plain code; runs both researchers in parallel with a time limit and search budget, then guardrails, verifier, writer. Returns a partial briefing if a researcher fails.
- `free_sources/`: optional free public sources, no API keys (see below).
- `live/`: paid provider clients (Tavily, People Data Labs, watsonx.ai, Gemini), date parsing and the `build_live_providers` factory (see below).
- `cli.py`: command-line entry point for the samples.
- `fixtures/`: the three fictional SAMPLE prospects (JSON).

## Where real providers plug in

`providers.py` defines the Protocols the agents depend on. Implement them and pass them to `run_research`; nothing else changes.

- `LLMClient`: IBM watsonx.ai likely, Gemini possible (undecided).
- `SearchClient`: Tavily.
- `ProfileClient`: People Data Labs.

API keys belong only in the research worker's environment variables, never in code or the repo.

## Free public sources (no API keys, no LLM)

`free_sources/` implements `SearchClient` and `ProfileClient` over free public data, so the orchestrator, guardrails, verifier and writer run unchanged. Facts come from structured fields (deterministic), each with a source URL, publisher and date.

- **Wikidata + Wikipedia** (`wikidata.py`): industry, headquarters, founded, official website, employee count (with its point-in-time date), current CEO, parent organization, plus the Wikipedia summary as an excerpt. If the company name matches more than one organization and the company domain does not settle it, nothing is returned and a note says so. Person facts only come from Wikidata when the name AND current employer both match exactly one person; otherwise person facts stay empty with a note.
- **SEC EDGAR** (`edgar.py`): US public companies only. SIC industry, business city/state (never the street address), ticker, latest 10-K/10-Q, and up to 3 dated 8-K filings from the last year as news. Skipped entirely (logged once) when `SEC_USER_AGENT` is unset.
- **Company homepage** (`homepage.py`): title and meta/og description, shown as "how the company describes itself" (attributed, not verified). Fetches only the prospect's company domain, or the website Wikidata lists for the matched company. It is https only, resolves the host and refuses non-public IPs (and connects to the validated IP), follows at most 3 same-host redirects, honors robots.txt, and uses a 5s timeout, a 1 MB cap and text/html only. At most one extra `/about` page, and only when the homepage has no description.
- **`http.py`**: the shared client (timeouts, retry with backoff on 429/5xx, User-Agent, size cap, request count and time budget taken from `Budget`: `4 x max_searches` requests, `timeout_seconds` wall clock).

Environment variables (all optional; never put values in the repo):

| Variable | Meaning |
|---|---|
| `RESEARCH_PROVIDERS` | Read by the backend worker. `free` enables these sources for prospects with no sample fixture. Unset keeps the offline default. |
| `SEC_USER_AGENT` | Descriptive User-Agent with contact info that SEC requires (for example `YourApp you@yourdomain`). Unset skips EDGAR. |
| `RESEARCH_CONTACT` | Optional contact text appended to the generic `ColdCallConversion/0.1 (research prototype)` User-Agent used for Wikimedia and company sites. |

Use it directly:

```python
from cold_call_agents.free_sources import build_free_providers
llm, search, profiles = build_free_providers(prospect, Budget())   # reads the env vars above
briefing = run_research(prospect, llm=llm, search=search, profiles=profiles, mode="live")
```

Limits: free sources rarely cover non-notable people, so person facts are usually empty; small or private companies often have no Wikidata entry; there is no news source except SEC 8-Ks; Wikidata facts can be old (each fact shows its date, and the verifier flags stale ones). The tests use fictional fixtures in `tests/data/free_sources/` and a mocked HTTP layer, so they run offline.

## Live providers (paid, keys required)

`live/` holds the real clients. They are fully tested offline against fictional recorded responses (`tests/data/live/`), so adding keys is the only step. No live call is ever made without a key. Template: [`.env.example`](.env.example) (empty values; real keys go only in the worker environment or an untracked `.env`).

```python
from cold_call_agents.live import build_live_providers
llm, search, profiles = build_live_providers(prospect, Budget())   # reads the env vars below
# call search.close() / profiles.close() / llm.close() (if present) when done
```

Any provider with a missing key falls back to the free sources (or template text for the LLM), with a note that reaches `missing`, so partial setups work. The backend switch (`RESEARCH_PROVIDERS=live`) is wired by the API lane, not here.

| Provider | Env vars | Setup |
|---|---|---|
| Tavily search (`live/tavily.py`) | `TAVILY_API_KEY` | Create a key at tavily.com, sent as a Bearer header. Uses `basic` depth (1 credit per search); the search budget caps calls per briefing. |
| People Data Labs (`live/pdl.py`) | `PDL_API_KEY`, `PDL_MIN_LIKELIHOOD` (default 6) | Create a key at peopledatalabs.com (X-Api-Key header). Matches below the likelihood threshold, no match (404) and multiple matches all become "no match" notes. |
| IBM watsonx.ai (`live/watsonx.py`) | `LLM_PROVIDER=watsonx` (default), `WATSONX_API_KEY` (IBM Cloud API key), `WATSONX_URL` (region base URL such as `https://us-south.ml.cloud.ibm.com`), `WATSONX_PROJECT_ID`, optional `WATSONX_MODEL_ID`, `WATSONX_API_VERSION` | Create a watsonx.ai project (Runtime service attached), copy its project id, and use the IBM Cloud API key. The key is exchanged for an IAM token (cached, refreshed 5 minutes before expiry, or after a 401). Default model `ibm/granite-3-3-8b-instruct`: a small IBM instruct model on watsonx.ai's supported list, cheap per token and enough for the short summaries and talking points. Check it is enabled in your region. |
| Gemini fallback (`live/gemini.py`) | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, optional `GEMINI_MODEL` | Create a key in Google AI Studio. Default model alias `gemini-flash-lite-latest`; pin a specific model id to avoid surprise changes. |

Docs the clients were written against: Tavily (docs.tavily.com/documentation/api-reference/endpoint/search), People Data Labs (docs.peopledatalabs.com person and company enrichment, fields, company-schema), watsonx.ai (cloud.ibm.com/apidocs/watsonx-ai, text chat), IBM IAM, Gemini (aistudio.google.com/api-reference/generate-content). Request and response shapes are recorded in each module's docstring.

Behavior worth knowing:

- Every call has a timeout (15s search/profiles, 30s LLM), at most one retry on 429/5xx, and shares the briefing's time budget. Errors, timeouts and bad responses become notes (search/profiles) or an `LLMError` that the writer already turns into a template fallback; keys never appear in notes.
- Privacy: PDL fields are read from an allowlist (name, current title, current employer, seniority, past employers, role start date; company name, website, industry, size, HQ city, founded). Personal emails, phones, home addresses and birth data are never read. Tavily text is sanitized (HTML, instruction-like sentences, phone numbers and addresses) before use.
- Dates: `live/dates.py` converts ISO, RFC 2822, "2024-05", "May 3, 2024" and epoch values to `YYYY-MM-DD`; anything else is undated. PDL records carry no reliable "as of" date, so their source date is the lookup day (the excerpt says the underlying data date is unknown).
- Token usage: `llm.usage` (`calls`, `input_tokens`, `output_tokens`) accumulates per client for later cost tracking.
- Limit: Tavily results carry no pre-extracted `claims`, and `extract_claims` in `researchers.py` is still the v0 stub. Until an LLM extraction step is added there, live search results become sources but not facts; PDL facts work now. That change is in `researchers.py` and needs its own task.
- Limit: the watsonx `version` date and default model id could not be fully verified without a key; both are env-configurable.

## Frontend limitation: `mode: "demo"`

The frontend `briefSchema` (`apps/web/src/lib/model.ts`) only accepts the literal `mode: "demo"`, so the adapter always emits `"demo"`. Showing live-mode briefings needs a frontend schema change agreed with Aanand.

## v0 limits

- Facts come from profile records and the pre-extracted `claims` on fixture search results (a stand-in for LLM extraction).
- Privacy filtering is simple regex/keyword rules.
- Independent sources are counted by distinct publisher.
- Staleness: role and company size are stale after 365 days; dated news (`recent_news.*`) is stale after 180 days and is then not used for talking points; a fact backed only by undated sources is stale.
- Budget: `Budget` caps searches (`max_searches`, default 6), profile lookups (`max_profile_lookups`, default 2) and time (`timeout_seconds`, default 60), split between the person and company researchers. A failing search or profile call is noted in `missing` and keeps whatever was already collected.
- If the LLM fails or returns private text, the writer falls back to a templated summary, skips that talking point, and notes it in `missing`.
- Multi-valued fields (news, talks) use one fact key per item, e.g. `recent_news.carrier_agreement`, so different items are not reported as conflicts.

## Before real providers

Not done in v0; decide or build these when swapping in real clients:

- **Typed profiles.** Profile lookups return plain dicts. Add `PersonProfile` / `CompanyProfile` models and map the People Data Labs response onto them (field names, missing fields, multiple matches).
- **Date parsing.** Source dates must be ISO `YYYY-MM-DD`; anything else becomes undated (and so stale). Real providers return other formats, so parse them before building a `Source`.
- **Request timeouts.** The orchestrator's time limit abandons slow researcher threads but cannot kill them. Real Tavily/People Data Labs/LLM clients need their own request timeouts so stragglers end.
- **Schema test is hand-copied.** `check_brief_schema` in the tests re-states `briefSchema` from `apps/web/src/lib/model.ts` by hand and can drift. Consider generating it from the zod schema or running a shared contract test.
- **`preparedAt` is nondeterministic.** It is the wall-clock time of generation; tests exclude it when comparing runs.
- **UX question for Aanand.** The adapter appends text suffixes such as "(unconfirmed: single source)", "(conflicting sources)" and "(may be out of date)" to fact text. Many facts end up carrying "(unconfirmed: single source)", which may be noisy. A structured per-fact status field in the frontend schema would let the UI decide how to show it.

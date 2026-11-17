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
- `metrics.py`: per-run time, request, token and estimated-cost tracking (placeholder price table).
- `evals/`: offline evaluation set (`cases/`), automatic checks and the runner (see below).
- `cli.py`: command-line entry point for the samples (`--eval` runs the evals).
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
- Tavily results carry no pre-extracted `claims`; their facts come from LLM claim extraction (below), which needs a real LLM (watsonx or Gemini).
- Limit: the watsonx `version` date and default model id could not be fully verified without a key; both are env-configurable.

## Evaluations and cost tracking

### Run the evals

```sh
cd apps/agents
.venv/bin/python -m evals.run                      # offline, mock providers, no network or keys
.venv/bin/python -m cold_call_agents.cli --eval    # same thing (source checkout only: evals/ is not packaged)
.venv/bin/python -m evals.run --case prompt_injection --report /tmp/report.json
```

`evals/cases/*.json` holds 21 fictional prospects (all SAMPLE data, recorded provider responses served by the mocks): a clean company, a private company, an ambiguous company name, a non-notable person, a famous namesake, a former employee, thin info, conflicting sources, stale data, prompt injection, private-data leaks, a German company, odd Wikidata-style categories, a search outage, a total miss, an unsourced fact, unsafe LLM output (private data, injection) and an unsure-identity case with person facts, plus the three shipped fixtures. Each case lists expected properties, not exact text: allowed `identity_match` values, `min_facts`/`max_facts`, `must_flag_uncertainty`, `must_not_contain`/`must_contain` strings, `must_have_status`, `min_stale_facts`/`max_stale_facts`, `no_person_facts`. Cases can also set `llm_text` (a mock LLM that always returns that text), `inject` (extra facts/sources/forced identity from the person researcher, to exercise guardrails and the writer). The run prints a summary table, writes a JSON report (default `evals/report.json`, git-ignored) and exits non-zero if any check fails. `tests/test_evals.py` runs the offline set, so CI enforces it.

### What is checked on every briefing

citations (every fact and talking point cites a source that exists), sources valid (each source has an http(s) URL; URLs are not fetched), no private data (guardrail phone/address/personal-email/family patterns), no instruction-like text, banned and required strings, uncertainty flagged where expected, fact count bounds, identity rules, person facts only when identity is not unsure, conflicting/stale statuses, frontend shape, and budget (research time, i.e. the slower researcher plus guardrails and verify, within `Budget.timeout_seconds` plus a 2s allowance; the writer is excluded; searches and profile lookups within their caps).

### Cost and speed numbers

`run_research_with_metrics(...)` (orchestrator.py) returns `(briefing, RunMetrics)`; `run_research` is unchanged. `RunMetrics` has wall seconds per stage (`person` and `company` run in parallel, so they overlap; `guardrails`, `verify`, `write`), search/profile/HTTP request counts, LLM calls and input/output tokens (read from the client's `usage`; template and mock LLMs report 0), and `est_cost_usd`. One `research_run {...json...}` line is logged per run on logger `cold_call_agents.metrics`, identified by `prospect_id` only. `python -m cold_call_agents.cli --sample northwind --metrics` prints it. Counts are per-run deltas. `http_requests` covers the free-source clients only (the live clients expose no counter yet), and sharing one client across concurrent runs mixes counts. If a researcher times out and is abandoned its stage time may be missing. Mock LLM calls are counted from `.calls`; watsonx and Gemini both expose `usage`.

Estimated cost = input tokens x input price + output tokens x output price (per 1M tokens, by model id) + searches x `search_per_request` + profile lookups x `profile_per_request`. The default prices in `cold_call_agents/metrics.py` are PLACEHOLDERS, not quotes; a model with no entry costs 0. Non-finite or negative prices, or any unreadable value, make the whole override fall back to the defaults with a warning. To update them without code changes set `CCC_PRICES` to inline JSON or a JSON file path:

```sh
export CCC_PRICES='{"models": {"gemini-flash-lite-latest": [0.10, 0.40], "ibm/granite-3-3-8b-instruct": [0.20, 0.20]}, "search_per_request": 0.008}'
```

### Compare models later (watsonx vs Gemini)

`--live` uses `build_live_providers` from the environment; `--free` uses `build_free_providers` (no keys, still network). They make real calls and may cost money, so they refuse to run (exit 2) when `CI` is set or under pytest, and also unless you opt in with `CCC_ALLOW_LIVE_EVAL=1`. The guard is also in `run_all`/`run_case`. The tests never use them. The cases only supply the prospects; the mock data and the facts-count expectations are for mock runs, so expect some expectation failures against real data and compare the reports, not the exit code.

```sh
export CCC_ALLOW_LIVE_EVAL=1 TAVILY_API_KEY=... PDL_API_KEY=... CCC_PRICES='{...}'          # set in your shell, never in files
LLM_PROVIDER=watsonx WATSONX_API_KEY=... WATSONX_URL=... WATSONX_PROJECT_ID=... \
  .venv/bin/python -m evals.run --live --case fixture_northwind --report /tmp/watsonx.json
LLM_PROVIDER=gemini GEMINI_API_KEY=... \
  .venv/bin/python -m evals.run --live --case fixture_northwind --report /tmp/gemini.json
```

Compare `totals` (seconds, tokens, est cost) and per-case `checks` between the two JSON reports. Limits: live search results have no pre-extracted claims until the LLM extraction step exists, so live fact counts will be low; there is no LLM quality grading yet.

## LLM claim extraction

`extraction.py` turns free-text search results (no pre-extracted `claims`) into facts when a real LLM is available. Fixtures with `claims`, the template/mock LLMs and a missing LLM behave exactly as before (no extraction, no fake facts).

The model returns a JSON array of `{key, value, quote}` per source. Prompts (`SYSTEM_PROMPT`, `USER_PROMPT`, `RETRY_SUFFIX`) are at the top of the module. Source text is sanitized (HTML, instruction-like sentences, private data) and placed inside a `<data>` block with `<`/`>` escaped; the model is told to ignore instructions in it. Precision over recall: every claim is checked, and dropped if any check fails:

- the key is on the allowlist: person `current_role`, `tenure`, `recent_talk.*`; company `industry`, `employee_count`, `headquarters`, `recent_news.*`. Slugs for the `.*` keys are a hash of source and sentence derived in code, never the model's text;
- the quote is exactly one full sentence of the sanitized content (`;` does not end a sentence; abbreviations like Inc., Jr., U.S. do not either; CJK full stops do). The fact text is that real sentence, not the model's string;
- the sentence BEGINS with the subject (person: full name, optional middle initial; company: its name, possessive allowed; single-word company names are case-sensitive), after at most a short opener like "In 2024,". Name matching ignores accents, apostrophes and hyphen style. A longer name ("Apple Valley", "Jane Doe Smith") is rejected;
- person keys: the sentence has no second person-like name, the value sits in the first clause (before ", and", " and <Name>", while, whereas, succeeded, replaced) after the subject with no other name in between, and for role/tenure any employer named (after at/for/of/with/by/from/joined/leads/runs/founded/heads) is the prospect's company;
- company keys: no other capitalized proper noun besides the subject (months, days, U.S.-style abbreviations; for headquarters also its value), so "Acme competes with Globex, which employs 650 people" is dropped;
- hedge, denial and past markers drop the claim for every key: not, n't, never, no longer, denied, rumor(s), reportedly, might, may, could, would, will, plans to, expected to, former, ex-, previously, until, left, retired, resigned, stepped down, succeeded, replaced, was (except "was promoted to/named/appointed" for roles). Roles and tenure also reject served, worked, held, spent, then, emeritus, interim, acting, incoming and year ranges; a role with an explicit year more than 2 years before the source date is dropped;
- the value is a contiguous run of words in the sentence;
- `employee_count` must be a number next to an employee/staff/people word, with no money, revenue, customers, users, other numbers, hypotheticals or place/site scope ("in Ohio", "at its plant");
- the quote is not instruction-like or private.

The fact's source is always the search result the model was shown (the model cannot add sources), and for LLM-extracted facts its excerpt (up to 600 chars) covers the matched sentence of every claim taken from that source. At most 4 claims per source.

Limits: invalid JSON gets one retry with a stricter instruction, then a note in `missing`; an LLM exception is not retried and is noted as an LLM error; nothing escapes. `Budget.max_extraction_calls` (default 6, retries count) is per researcher: the person and the company researcher each get a copy, so the effective cap is 2x per briefing (12) until the orchestrator splits it. Matching is conservative (token and capitalization heuristics), so paraphrases, multi-sentence facts and sentences with extra capitalized names are dropped. Tests use a scripted fake LLM (`tests/test_extraction.py`, `tests/test_extraction_adversarial.py`).

## Frontend limitation: `mode: "demo"`

The frontend `briefSchema` (`apps/web/src/lib/model.ts`) only accepts the literal `mode: "demo"`, so the adapter always emits `"demo"`. Showing live-mode briefings needs a frontend schema change agreed with Aanand.

## v0 limits

- Facts come from profile records, the pre-extracted `claims` on fixture search results, and guarded LLM extraction from live search text (see "LLM claim extraction").
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

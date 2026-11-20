# Cold Call Conversion: Backend API & Research Worker (Lane C)

FastAPI backend service and asynchronous research job worker for Cold Call Conversion.

## Overview

- **FastAPI application**: Implements REST endpoints for calling lists, prospects, CSV bulk upload, reordering, call sessions, and research triggers.
- **Background Research Worker**: Consumes queued research jobs, invokes `cold_call_agents`, enforces stale-revision protection, and caches briefings.
- **Storage Layer**: Dual support for in-memory repository (local dev & testing) and IBM Cloud Databases for MongoDB (`pymongo`).
- **Security & Multi-Tenancy**: Scopes every request to the authenticated `seller_id` (BOLA protection), enforces strict input validation, avoids logging PII, and returns generic errors to clients.

## API Endpoints

- `GET /healthz` - Health and liveness probe
- `GET /v1/workspace` - Full workspace state hydration
- `GET /v1/lists` - List all calling lists for seller
- `POST /v1/lists` - Create a calling list (max 50)
- `PATCH /v1/lists/{id}` - Rename list
- `DELETE /v1/lists/{id}` - Delete list and associated prospects
- `GET /v1/lists/{id}/prospects` - Fetch prospects for a list
- `POST /v1/lists/{id}/prospects` - Add prospects (single or batch)
- `POST /v1/lists/{id}/import` - Upload and parse CSV calling list (up to 500 rows)
- `PATCH /v1/prospects/{id}` - Update prospect (increments revision, resets brief)
- `DELETE /v1/prospects/{id}` - Delete prospect
- `POST /v1/prospects/{id}/move` - Reorder prospect
- `POST /v1/research` - Enqueue research jobs for prospect IDs (idempotent)
- `GET /v1/prospects/{id}/research` - Read research status and brief
- `GET /v1/calls/active` - Check currently active call
- `POST /v1/calls` - Connect call (only 1 active at a time)
- `POST /v1/calls/end` - End call with outcome (supports `Idempotency-Key`)
- `POST /v1/calls/reset/{prospect_id}` - Reset call status

OpenAPI specification is available at `docs/api/openapi.json` and interactively at `/docs` when running the server.

## Authentication

Set `AUTH_MODE` to one of:

- `jwt` (required for any deployed environment): `Authorization: Bearer <JWT>`. The token must be signed with `JWT_SECRET` (algorithm `JWT_ALGORITHM`, default HS256) and carry `exp` and a `sub` (or `seller_id`) claim, which becomes the seller. Invalid, expired, unsigned or unsupported tokens get `401`. `X-Seller-ID` is ignored. If `JWT_SECRET` is empty, every request gets `401`.
- `dev` (default, local only): `X-Seller-ID` header, else `DEFAULT_DEV_SELLER_ID`. Never deploy with this mode.

Any other value fails closed with `401`.

Set `ENVIRONMENT` to say where the service runs. Dev auth (`AUTH_MODE=dev`) is only accepted when `ENVIRONMENT` is `development`, `local` or `test`; any other value refuses dev auth.

> **Warning:** in any deployed environment set `AUTH_MODE=jwt` and `ENVIRONMENT=production`. `ENVIRONMENT` defaults to `development`, so leaving it unset keeps dev auth, which trusts the `X-Seller-ID` header.

## Research behaviour

- `POST /v1/research` is idempotent: a prospect with a queued or running job for its current revision is skipped, so the response lists only newly created jobs.
- Prospects that match a sample fixture (northwind, harborview, cedarridge) get sample briefings. Any other prospect gets a `partial` briefing with no facts and an uncertainty note, until live Tavily/People Data Labs/LLM providers are connected (Lane B). Nothing is invented.

## Run with Docker (API + MongoDB + web)

From the repo root:

```bash
cp .env.example .env     # set MONGO_ROOT_PASSWORD to a long random value (letters and digits)
docker compose up --build
```

The API runs on http://127.0.0.1:8000 with `ENVIRONMENT=development`, `AUTH_MODE=dev` and `STORAGE_BACKEND=mongodb`, talking to the compose MongoDB (credentials from `.env`, which is git-ignored). `docker compose down -v` also removes the database volume. The API image (`apps/api/Dockerfile`) must be built with the **repository root** as context because it installs `apps/agents`; compose does this for you. It needs `BIND_HOST` (a specific address) and has no all-interfaces default.

Local development only. For deployed use set `AUTH_MODE=jwt`, `JWT_SECRET`, `ENVIRONMENT=production`, and a TLS `MONGODB_URI` (for example IBM Cloud Databases for MongoDB). `STORAGE_BACKEND=mongodb` without `MONGODB_URI` refuses to start instead of silently using the in-memory store.

### MongoDB storage tests

`tests/test_mongo_storage.py` runs the storage layer (and one HTTP flow) against a real MongoDB. It is **skipped unless `MONGO_URL` is set**, so normal `pytest` runs stay offline. Each run uses a throwaway database that is dropped afterwards.

```bash
docker compose up -d mongo
set -a; . ./.env; set +a      # from the repo root
cd apps/api
export MONGO_URL="mongodb://${MONGO_ROOT_USERNAME}:${MONGO_ROOT_PASSWORD}@127.0.0.1:27017/?authSource=admin"
uv run --extra dev --extra mongodb pytest tests/test_mongo_storage.py -v
```

## Prospect company domain

`companyDomain` is optional on create, `PATCH`, and CSV import (header aliases: `website`, `domain`, `company website`, `company domain`, `url`). It is normalized to a bare lowercase hostname (scheme, path, port and a leading `www.` removed). IP addresses, credentials, invisible characters, reserved suffixes (`.local`, `.internal`, `.test`, `.localhost` and similar), non-http(s) schemes and invalid hostnames return `422` (CSV rows are rejected individually). On `PATCH`, omit it to keep the value or send `""` to clear it. Changing it bumps the prospect revision, clears the brief, and changes the brief cache key.

## Research retries and brief cache

A research attempt that fails with an exception is retried automatically with jittered exponential backoff. After the last attempt the prospect stays `failed` with a generic error. Stale prospects (edited meanwhile) and deterministic errors (validation or programming errors) are never retried. Validation `422` responses do not echo the rejected input. Cached briefs older than the cache window are ignored on read.

- `RESEARCH_MAX_ATTEMPTS`: total attempts per job (default `3`).
- `RESEARCH_RETRY_BASE_SECONDS`: backoff base (default `5`; delays about 5 s, 10 s, 20 s, +/-25%).
- `BRIEF_CACHE_DAYS`: how long a cached brief stays valid (default `7`).
- `RESEARCH_LEASE_SECONDS` (default `90`) and `RESEARCH_TIMEOUT_SECONDS` (default `60`) as before.

## OpenAPI export

Regenerate `docs/api/openapi.json` from the app after changing routes or models:

```bash
cd apps/api
.venv/bin/python scripts/export_openapi.py   # optional argument: output path
```

## Local Development & Testing

```bash
cd apps/api
uv run --extra dev pytest -v   # add --extra mongodb to use STORAGE_BACKEND=mongodb
```

Without uv, use pip (the agents package is a local dependency):

```bash
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -e ../agents -e '.[dev]'
.venv/bin/pytest -q
```

### Research providers

`RESEARCH_PROVIDERS` (read from the worker's environment; the active mode is logged at startup) selects how prospects without a sample fixture are researched. Sample fixtures for the fictional sample prospects always win in every mode.

- unset (default): no network; non-sample prospects get an empty, partial brief.
- `free`: free public sources (Wikidata/Wikipedia, SEC EDGAR, company homepage), no API keys, no LLM. Optional: `SEC_USER_AGENT` (required by SEC, otherwise EDGAR is skipped), `RESEARCH_CONTACT`.
- `live`: paid providers via `cold_call_agents.live.build_live_providers`. Env vars: `TAVILY_API_KEY` (web search), `PDL_API_KEY` and `PDL_MIN_LIKELIHOOD` (people data), `LLM_PROVIDER` (`watsonx` default, or `gemini`), `WATSONX_API_KEY` + `WATSONX_URL` + `WATSONX_PROJECT_ID` (optional `WATSONX_MODEL_ID`, `WATSONX_API_VERSION`), or `GEMINI_API_KEY` (optional `GEMINI_MODEL`). Template: [`.env.example`](.env.example) (empty values; real keys only in the environment or an untracked `.env`).
- Any other value is treated as unset, with a one-time warning.

Fallbacks in `live`: a missing Tavily key uses free sources for search, a missing PDL key uses free sources for profiles, and a missing LLM setting uses template text. Each fallback is noted in the brief's uncertainty list, so partial key setups work.

Caching: in `free` and `live` only complete (`ready`) briefs are cached, never partial ones, and the mode is part of the cache key, so a brief from one mode is never served after switching to another.

Cost warning: `live` mode spends paid credits (Tavily, People Data Labs, watsonx.ai or Gemini) on every uncached research. A failed attempt is retried up to `RESEARCH_MAX_ATTEMPTS` times and each retry can repeat the paid calls, so lower it (for example to `1`) while testing.

`GET /healthz/research` (requires the same authentication as the research routes) reports the mode and which providers are configured as booleans only, never key values, for example `{"mode":"live","tavily":true,"pdl":false,"llm":"watsonx","watsonx":false,"gemini":false}` (`watsonx` is true only when the key, an https URL and the project id are all set). With the variable unset, `mode` is `"default"`.

Prospects may carry an optional `companyDomain` (see below). When set it is passed to the agents; otherwise the homepage fetched is the website Wikidata lists for the matched company. Details and limits: [apps/agents/README.md](../agents/README.md).

To run the local API server:

```bash
cd apps/api
uv run uvicorn cold_call_api.main:app --host 127.0.0.1 --port 8000 --reload
```

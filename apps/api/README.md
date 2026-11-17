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

By default the worker uses sample fixtures for the fictional sample prospects and gives every other prospect an empty (no-facts) brief, with no network calls. Set `RESEARCH_PROVIDERS=free` to research other prospects from free public sources (Wikidata/Wikipedia, SEC EDGAR, the company homepage; no API keys, no LLM). Related variables, all read from the worker's environment:

- `RESEARCH_PROVIDERS`: `free` to enable; anything else (or unset) keeps the default.
- `SEC_USER_AGENT`: descriptive User-Agent with contact info, required by SEC. Without it, EDGAR is skipped.
- `RESEARCH_CONTACT`: optional contact text added to the generic User-Agent sent to Wikimedia and company sites.

Prospects may carry an optional `companyDomain` (see below). When set it is passed to the agents; otherwise the homepage fetched is the website Wikidata lists for the matched company. Details and limits: [apps/agents/README.md](../agents/README.md).

To run the local API server:

```bash
cd apps/api
uv run uvicorn cold_call_api.main:app --host 127.0.0.1 --port 8000 --reload
```

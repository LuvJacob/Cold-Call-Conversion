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

## Research behaviour

- `POST /v1/research` is idempotent: a prospect with a queued or running job for its current revision is skipped, so the response lists only newly created jobs.
- Prospects that match a sample fixture (northwind, harborview, cedarridge) get sample briefings. Any other prospect gets a `partial` briefing with no facts and an uncertainty note, until live Tavily/People Data Labs/LLM providers are connected (Lane B). Nothing is invented.

## Local Development & Testing

```bash
cd apps/api
uv run --extra dev pytest -v   # add --extra mongodb to use STORAGE_BACKEND=mongodb
```

To run the local API server:

```bash
cd apps/api
uv run uvicorn cold_call_api.main:app --host 127.0.0.1 --port 8000 --reload
```

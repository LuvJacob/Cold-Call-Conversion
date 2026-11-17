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

## Local Development & Testing

```bash
cd apps/api
uv run --extra dev pytest -v
```

To run the local API server:

```bash
cd apps/api
uv run uvicorn cold_call_api.main:app --host 127.0.0.1 --port 8000 --reload
```

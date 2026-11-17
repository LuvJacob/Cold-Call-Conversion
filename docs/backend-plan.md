# Backend Plan (Lane C)

**Owner:** Srikar Satluri / James Afon (Lane C). **Status:** Approved Architecture & Implementation Plan.
**Basis:** README, `docs/agent-design.md`, `docs/frontend-integration.md`, `apps/agents/`, `apps/web/src/lib/model.ts`.

---

## 1. What Lane C Delivers

From the README (Lane C) and frontend handoff:

1. API for lists, prospects, CSV import, ordering, and call sessions/outcomes, with ownership checks per seller.
2. Start research for a prospect or list; read per-prospect status, errors, retry state, and the finished briefing.
3. Store and cache briefings; never research the same prospect twice within the cache window.
4. Run James's agents (`apps/agents`, `run_research(...)`) from a worker / background task engine, with timeouts, retries, and stale-result protection.
5. Publish the API contract (OpenAPI + example payloads) that Aanand (Frontend) builds against.
6. Keep it secure, reliable, and fast (README rules + IBM security policy).

---

## 2. Architecture & Data Flow

```
Seller browser (Next.js, Lane D)
      | HTTPS + Bearer token
      v
FastAPI Backend ("apps/api")  ---->  Repository Layer (In-Memory / MongoDB)
      | writes job doc                       ^
      v                                      |
 research_jobs queue  <--- claims ---  Background Research Worker
                                        runs cold_call_agents.run_research
                                             |            |
                                             v            v
                                       LLMClient     Search & Profile Clients
```

---

## 3. Data Model

All documents carry `seller_id`; **every query filters on it** (ownership check on every request).

| Entity | Fields | Description |
|---|---|---|
| `List` | `id`, `seller_id`, `name`, `created_at` | Max 50 per seller. |
| `Prospect` | `id`, `seller_id`, `list_id`, `name`, `company`, `role`, `phone`, `notes`, `position`, `revision`, `prospect_key`, `research_status`, `research_error`, `brief`, `call_status`, `outcome` | `revision` increments on every edit (stale-result guard). `prospect_key` = hash of normalized (name, company, role). |
| `Briefing` | `id`, `prospect_key`, `mode`, `prepared_at`, `payload` | Cached briefing by `prospect_key`. |
| `ResearchJob` | `id`, `prospect_id`, `seller_id`, `revision`, `status`, `attempts`, `lease_expires_at`, `claimed_by`, `last_error`, `created_at` | Status: `queued`, `running`, `ready`, `partial`, `failed`. |
| `Call` | `id`, `seller_id`, `prospect_id`, `started_at`, `ended_at`, `outcome`, `idempotency_key` | Connect and end calls with idempotency. |

---

## 4. API Endpoints

- `GET /healthz` - Health probe
- `GET /v1/lists` - List all lists for the seller
- `POST /v1/lists` - Create a list
- `PATCH /v1/lists/{id}` - Rename list
- `DELETE /v1/lists/{id}` - Delete list and associated prospects
- `GET /v1/lists/{id}/prospects` - Get prospects for a list
- `POST /v1/lists/{id}/prospects` - Add prospects (single or batch)
- `POST /v1/lists/{id}/import` - Upload and parse CSV calling list
- `PATCH /v1/prospects/{id}` - Update prospect (increments revision, resets brief)
- `DELETE /v1/prospects/{id}` - Delete prospect
- `POST /v1/prospects/{id}/move` - Reorder prospect
- `POST /v1/research` - Enqueue research jobs for prospect IDs (idempotent)
- `GET /v1/prospects/{id}/research` - Read research status and brief
- `POST /v1/calls` - Connect call
- `POST /v1/calls/{id}/end` - End call with outcome

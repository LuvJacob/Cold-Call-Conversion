# Backend Plan (Lane C)

**Status: current state of what is built on `main` (`apps/api`), plus open decisions.** This replaces the original approved-plan draft. Parts of Srikar's longer IBM Cloud draft (`origin/backend/plan`) that still apply are folded in under "Deployment ideas" and are proposals only: no IBM Cloud resources are provisioned yet.
**Basis:** `apps/api/README.md`, `docs/frontend-integration.md`, `docs/agent-design.md`, `apps/agents/`, `apps/web/src/lib/model.ts`.

---

## 1. What is built

A FastAPI service (`apps/api/cold_call_api`) with a research worker that runs inside the API process.

```
Seller browser (Next.js, Lane D)
      | HTTPS, Authorization: Bearer <JWT> (or X-Seller-ID in dev)
      v
FastAPI app ----> StorageRepository (memory | MongoDB)
      | POST /v1/research writes a job, schedules BackgroundTasks
      v
process_job (in-process worker) -- claims job with a lease --> cold_call_agents.run_research
                                                                (sample fixtures, or free public sources)
```

- **Storage:** `STORAGE_BACKEND=memory` (default, local dev and tests) or `mongodb` (`pymongo`, `MONGODB_URI`, `MONGODB_DB_NAME`). Both implement one `StorageRepository` interface and are covered by the same behaviour.
- **Worker:** `BackgroundTasks` runs `services/worker.py:process_job` for each enqueued job in the API process. There is no separate queue service. `run_worker_loop` exists for a standalone poller but is not deployed.
- **Auth modes:** `AUTH_MODE=jwt` (HS256 by default, `JWT_SECRET`, `exp` plus `sub` or `seller_id` required) for any deployed environment; `AUTH_MODE=dev` (`X-Seller-ID` header) only when `ENVIRONMENT` is `development`, `local` or `test`. Anything else returns 401. Every query is scoped by `seller_id` (other sellers' ids return 404).
- **Contract:** `docs/api/openapi.json`, regenerated with `apps/api/scripts/export_openapi.py`. The frontend contract in `apps/web/src/lib/model.ts` is only extended with optional fields.

## 2. Endpoints

`GET /healthz`; `GET /v1/workspace`; lists (`GET/POST /v1/lists`, `PATCH/DELETE /v1/lists/{id}`); prospects (`GET/POST /v1/lists/{id}/prospects`, `POST /v1/lists/{id}/import` for CSV up to 500 rows, `PATCH/DELETE /v1/prospects/{id}`, `POST /v1/prospects/{id}/move`); research (`POST /v1/research`, `GET /v1/prospects/{id}/research`); calls (`GET /v1/calls/active`, `POST /v1/calls`, `POST /v1/calls/end` with `Idempotency-Key`, `POST /v1/calls/reset/{prospect_id}`). Details: `apps/api/README.md`.

## 3. Data model

All documents carry `sellerId`; every query filters on it.

| Entity | Notes |
|---|---|
| List | Max 50 per seller. |
| Prospect | `name`, `company`, `role`, `phone`, `notes`, optional `companyDomain`, `position`, `revision`, `researchStatus`, `researchError`, `brief`, `callStatus`, `outcome`. `revision` bumps on every edit (including `companyDomain`), which clears the brief and guards against stale results. |
| Brief cache | Keyed by seller, list, name, company, role, normalized notes and `companyDomain`; entries store `savedAt`. |
| Research job | `prospectId`, `revision`, `status`, `attempts`, `leaseExpiresAt`, `claimedBy`, `lastError`. |
| Call | Active call (one per seller) and completed calls with an optional idempotency key. |

**companyDomain:** optional. Accepted as a website or domain; stored as a bare lowercase hostname (scheme, path, port and a leading `www.` removed; credentials rejected). IP literals, credentials, invisible characters, reserved suffixes (`.localhost`, `.local`, `.internal`, `.localdomain`, `.test`, `.invalid`, `.arpa`), non-http(s) schemes and invalid hostnames are rejected with a 422 (CSV rows are rejected individually). On PATCH, omit to keep, `""` to clear. CSV header aliases: `website`, `domain`, `company website`, `company domain`, `url`. It is passed to the agents as `company_domain`.

## 4. Research behaviour

- **Idempotency:** a prospect with a queued or running job for its current revision is skipped by `POST /v1/research`. Jobs whose lease expired (crash or restart) are failed and replaced on re-enqueue.
- **Stale-revision protection:** results are written only with a conditional update on `revision`. An edit during research discards the result; a stale job is dropped without retry.
- **Lease:** a claimed job holds a lease of `RESEARCH_LEASE_SECONDS` (default 90). Each agent run has `RESEARCH_TIMEOUT_SECONDS` (default 60).
- **Retries:** a failed attempt (exception in the pipeline) is retried automatically, up to `RESEARCH_MAX_ATTEMPTS` total attempts (default 3), with exponential backoff `RESEARCH_RETRY_BASE_SECONDS * 2^(attempt-1)` (default base 5 s, so about 5 s then 10 s), jittered by +/-25% and capped at 5 minutes. Attempts are tracked in the job's `attempts` field. Between attempts the job is requeued with a live lease and re-claimed; the worker re-checks the prospect revision before each retry. Only likely-transient errors are retried: pydantic `ValidationError`, `TypeError`, `KeyError`, `AttributeError` and `AssertionError` (our own bugs or bad data) fail immediately. While waiting, the job is `queued` with a `notBefore` time, so a poller (`run_worker_loop`) cannot claim it early; re-enqueue stays idempotent. If the job was taken over meanwhile (lease expired), the old runner abandons it without touching the prospect. After the last attempt the prospect stays `failed` with a generic user-safe error (no internal details). Retries are in-process: if the API process restarts during backoff, the job's lease expires and the next `POST /v1/research` replaces it.
- **Brief cache:** only briefs that contain facts are cached (free-source briefs only when complete). On read, entries older than `BRIEF_CACHE_DAYS` (default 7) are ignored and deleted. Freshness is checked in code, not with a TTL index. A cache hit is checked before any provider is called.
- **Providers:** sample fixtures for the fictional sample prospects; `RESEARCH_PROVIDERS=free` enables Wikidata/Wikipedia, SEC EDGAR and the company homepage (uses `companyDomain` when set). Otherwise a no-facts `partial` brief. Nothing is invented.

## 5. Deployment ideas (proposals, not provisioned)

From Srikar's draft; verify each against the real IBM account before depending on it.

- **API:** IBM Cloud Code Engine app (listens on `PORT`; consider min scale 1 for demos). **Worker:** today the in-process worker; a Code Engine daemon job running `run_worker_loop` is the path if it moves out.
- **Database:** IBM Cloud Databases for MongoDB (Standard plan, private endpoint, TLS with the service CA certificate; works with `pymongo`). Rough cost about $200/month at the smallest size. Databases for PostgreSQL is cheaper but conflicts with the team's NoSQL direction and the nested brief document.
- **Queue:** MongoDB-backed jobs with an atomic claim and lease (what the Mongo repository does) rather than RabbitMQ; Redis pub/sub is not durable and is unsuitable.
- **LLM:** watsonx.ai vs Gemini is Lane B's decision. **Secrets:** Code Engine secrets as env vars, Secrets Manager later. **Logs:** IBM Cloud Logs; never log prospect PII, phones or tokens.
- **Containers:** non-root user, minimal base image, vulnerability scan, committed lock files. Do not bind `0.0.0.0` without raising it first (`HOST` defaults to `127.0.0.1`).
- **Data to protect:** phone numbers and notes are PII; confirm at-rest encryption for the database.

## 6. Open decisions

1. **JWT issuer:** current mode is a shared-secret HS256 token. Which identity provider issues tokens (OIDC/SAML per policy), and do we verify via JWKS with issuer and audience checks? Aanand's handoff says not to assume Supabase.
2. **Real queue vs in-process worker:** is `BackgroundTasks` enough for the demo, or do we run a separate worker (Code Engine daemon job, or a queue service)? In-process work is lost on restart (recovered only by lease expiry and a new enqueue).
3. **IBM Cloud database choice:** Databases for MongoDB (current code) vs PostgreSQL; which plan and region the enterprise access covers.
4. **Deployment:** Code Engine app and job layout, private networking to the database, secrets handling, region.
5. **"Seller cadence data":** what it is (follow-up schedules, call history) and whether it needs its own collection.
6. **Cache window and retry limits:** defaults (7 days, 3 attempts, 5 s base) are proposals for James and Srikar to confirm.

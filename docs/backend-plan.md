# Backend Plan (Lane C)

**Owner:** Srikar Satluri (Lane C). **Status:** Living draft. Expect changes over the next few sessions; nothing here is final until the open decisions in section 9 are answered. Services and plans are proposals, and no IBM Cloud resources have been provisioned yet.
**Basis:** README, `docs/agent-design.md`, `docs/frontend-integration.md`, `apps/agents/`, `apps/web/src/lib/model.ts` as of `main` @ f9fb8d2, plus IBM Cloud docs searched for this draft.
**Shared interfaces:** the API contract and briefing format here are proposals. Per the README workflow, nothing is built against them until the affected owners (James, Aanand, Joseph) agree.

Items marked **[VERIFY]** are things I could not confirm from the docs available to me and must be checked in the real account before we depend on them.

---

## 1. What Lane C must deliver

From the README (Lane C) and Aanand's handoff list:

1. API for lists, prospects, CSV import, ordering, and call sessions/outcomes, with ownership checks per seller.
2. Start research for a prospect or list; read per-prospect status, errors, retry state, and the finished briefing.
3. Store and cache briefings; never research the same prospect twice within the cache window.
4. Run James's agents (`apps/agents`, `run_research(...)`) from a worker, with timeouts, retries, and stale-result protection.
5. Publish the API contract (OpenAPI + example payloads) that Aanand builds against.
6. Keep it secure, reliable, and fast (README rules + our security policy).

Out of scope: agent prompts/logic (James), UI (Aanand), requirements (Joseph).

## 2. Proposed IBM Cloud architecture

```
Seller browser (Next.js, Aanand)
      | HTTPS + OIDC bearer token
      v
Code Engine APP: FastAPI "api"  ---->  Databases for MongoDB (private endpoint, TLS)
      | writes job doc                      ^
      v                                     |
 research_jobs collection  <--- claims ---  Code Engine JOB (daemon mode): "worker"
                                            runs cold_call_agents.run_research
                                                 |            |
                                                 v            v
                                           watsonx.ai    Tavily / People Data Labs
                                         (LLMClient)     (SearchClient / ProfileClient)

Cross-cutting: Secrets (Code Engine secrets -> env vars), IAM, Cloud Logs, Container Registry
```

### Service choices and why

| Concern | Proposed service | Evidence from IBM docs | Notes / risks |
|---|---|---|---|
| API hosting | **Code Engine app** | Scales 0..N (default max 10); request timeout default 300s, max 600s; listens on `PORT` (default 8080); can be set to private visibility with `--visibility=private`. | Cold start when scaled to zero. Consider min scale 1 for demos. 40 apps/project limit is not a concern. |
| Worker hosting | **Code Engine job, `daemon` mode** | Daemon jobs have no max execution time, restart automatically on non-zero exit, need no HTTP port. You pay while it runs. | Worker must exit non-zero on fatal error so it restarts. `array` size gives parallel workers. |
| Database | **Databases for MongoDB, Standard plan** | JSON document store; Standard = daily automated backups + on-demand; private endpoints recommended; TLS with provided CA cert; works with pymongo. Lowest config about $202/month (0.5 vCPU, 4 GB, 10 GB, 3 members). | Matches the team's "NoSQL for seller cadence data" direction. **[VERIFY]** that free enterprise access covers it. Enterprise plan (PITR) needs Isolated Compute, from about $4,734/month for 8 vCPU: not justified for MVP. |
| Job queue | **MongoDB collection (`research_jobs`)** with atomic claim + lease | RabbitMQ is the alternative (about $229/month minimum, 3 members). Redis Pub/Sub is at-most-once and not persisted, so it is **unsuitable**. | Removes one service and one bill. Revisit RabbitMQ only if throughput requires it. |
| LLM | **watsonx.ai** (Granite / hosted models) | Python SDK `ibm_watsonx_ai`; Lite plan: 300,000 tokens/month, 2 req/s; Standard/Essentials: billed per 1,000 tokens (RU), 8 req/s. Granite 4 models advertise tool-calling and instruction following. | LLM choice is James's call (Gemini vs watsonx.ai is open). Lite is far too small for real testing. **[VERIFY]** which plan our enterprise account has. |
| Secrets | **Code Engine secrets** (to env vars); **Secrets Manager** as a later upgrade | Code Engine secrets map to env vars; 100 secrets/project; a secret update needs a new app revision or job run. Secrets Manager supports rotation. | Matches agent-design rule: keys only in the worker's environment. |
| Identity for services | **IAM**: least-privilege access policies; prefer **trusted profiles** over long-lived API keys for compute | IAM docs recommend trusted profiles for workloads. | **[VERIFY]** trusted-profile support for Code Engine specifically. MongoDB itself uses username/password, so those still live in secrets. |
| Logs | **IBM Cloud Logs** | Ingests app logs; alerting via Event Notifications. | Never log prospect PII, phones, tokens (security policy). Structured JSON logs. |
| Images | **Container Registry** (IBM) for built images | | See section 7 for base-image policy. |

Not researched (not in the doc libraries available to me): Cloudant, Event Streams (Kafka), Key Protect, App ID / Security Verify SaaS. I will not recommend them without checking.

### Rejected options (with reason)

- **Databases for PostgreSQL** (about $82/month minimum): cheaper and relational, but the team's current direction is NoSQL and the briefing is a nested JSON document. Only revisit if the team insists on SQL.
- **Redis as queue**: delivery is at-most-once and not persisted, so jobs can be lost.
- **Code Engine fleets/functions**: built for large parallel batch or short (under 2 minute) tasks; our worker is a long-lived poller.
- **Kubernetes Service / OpenShift**: more control than a hackathon MVP needs.

## 3. Data model (MongoDB), proposed

All documents carry `seller_id`; **every query filters on it** (ownership check on every request).

| Collection | Key fields | Notes |
|---|---|---|
| `sellers` | `_id`, `external_subject` | Created on first login. Minimal PII. |
| `lists` | `_id`, `seller_id`, `name`, `created_at` | Max 50 per seller (matches frontend). |
| `prospects` | `_id`, `seller_id`, `list_id`, `name`, `company`, `role`, `phone`, `notes`, `position`, `revision`, `prospect_key`, `research_status`, `research_error`, `brief_id`, `call_status`, `outcome` | `revision` bumps on every edit (stale-result guard). `prospect_key` = hash of normalized (name, company, role) for duplicates and cache. |
| `briefings` | `_id`, `prospect_key`, `schema_version`, `mode`, `generated_at`, `payload` | Payload = James's frontend-shaped brief (one JSON field). Cache entries shared by `prospect_key`. |
| `research_jobs` | `_id`, `prospect_id`, `seller_id`, `revision`, `status`, `attempts`, `lease_expires_at`, `claimed_by`, `last_error`, `created_at` | Status: `queued, running, done, partial, failed`. Unique index on (`prospect_id`, `revision`) for idempotent enqueue. |
| `calls` | `_id`, `seller_id`, `prospect_id`, `started_at`, `ended_at`, `outcome`, `idempotency_key` | Unique index on (`seller_id`, `idempotency_key`). |

Design rules (from Aanand's list):
- **Stale results:** worker writes the briefing only with a conditional update `where prospect.revision == job.revision`. An edit bumps the revision, so older results are dropped.
- **Idempotency:** `Idempotency-Key` header on call-end and enqueue; duplicate keys return the original result.
- **Cache:** at enqueue time, look up a `briefings` doc for the same `prospect_key` newer than the cache window (proposal: 30 days, answer to James's Q7). Worker re-checks before spending API credits. The freshness check is in code; do **not** use a TTL index that would delete briefings still referenced by prospects.
- **Queue claim:** `find_one_and_update` on `status=queued` (or expired lease) setting `status=running`, `lease_expires_at=now+90s`, incrementing `attempts`. Worker extends the lease while running. Dead workers' jobs become claimable again after the lease. Max attempts 3 (proposal, answer to James's Q4); then `failed`.
- **Sensitive data:** phone numbers and notes are PII. **[VERIFY]** at-rest encryption defaults for Cloud Databases; consider customer-managed keys if required.

## 4. API surface (v1, OpenAPI first)

Auth: `Authorization: Bearer <OIDC JWT>`; validated against issuer JWKS (issuer, audience, expiry, signature). Provider is an **open decision** (see section 9).

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/v1/lists`, PATCH/DELETE `/v1/lists/{id}` | List CRUD |
| GET | `/v1/lists/{id}/prospects?cursor=&limit=` | Paginated prospects incl. status + brief |
| POST | `/v1/lists/{id}/prospects` | Create 1..N prospects (JSON); returns per-row validation errors + duplicates |
| POST | `/v1/lists/{id}/import` | CSV upload (size/row caps, strict validation) |
| PATCH/DELETE | `/v1/prospects/{id}` | Edit (bumps `revision`, clears brief) / delete |
| POST | `/v1/prospects/{id}/move` | Reorder |
| POST | `/v1/research` | Body: prospect ids. Enqueues (idempotent), returns job states |
| GET | `/v1/prospects/{id}/research` | Status, error, attempts, brief |
| POST | `/v1/calls`, `/v1/calls/{id}/end` | Connect / end with outcome (idempotent). Never triggers research. |
| GET | `/healthz` | Liveness for Code Engine |

Conventions: stable string IDs, ISO-8601 UTC timestamps, RFC 9457 problem+json errors with **generic** messages (details logged server-side only), request size limits, rate limiting per seller.

Briefing payload v1 = existing `briefSchema` (`mode, preparedAt, summary, facts[{label,text,sourceIds}], sources[], questions[], roleContext, uncertainty[]`), plus a `schemaVersion` field. Two requests for the other lanes (not mine to decide): a structured per-fact status instead of text suffixes (James/Aanand), and allowing `mode: "live"` (Aanand).

## 5. Phased plan

Each phase = small PR on a `backend/<name>` branch, agreed with affected owners before merge (README workflow). Sample data is labeled as sample.

| # | Phase | Output | Depends on |
|---|---|---|---|
| 0 | **Decisions + provisioning** | Section 9 answered; IBM project, MongoDB, Code Engine project, IAM, watsonx.ai instance created (no secrets in repo) | Your approval, account access |
| 1 | **API contract** `backend/api-contract` | `docs/api/openapi.yaml`, example payloads (from James's fixtures), pydantic models | Phase 0 decisions on auth/DB shape |
| 2 | **Service skeleton** `backend/skeleton` | `apps/api/` FastAPI app, config from env vars, `/healthz`, structured logging, tests, lint/typing, lock file | 1 |
| 3 | **Persistence + CRUD + CSV** | Repository layer over MongoDB, lists/prospects/CSV import, pagination, duplicate rules | 2, MongoDB instance |
| 4 | **Auth + ownership** | JWT verification, per-seller scoping tests (BOLA tests), rate limits | Auth provider decision |
| 5 | **Jobs + worker** | `research_jobs` queue, `apps/worker/` entrypoint calling `run_research` with SAMPLE providers first, retries, leases, stale-result guard, call endpoints | 3; James's `run_research` interface (exists) |
| 6 | **Deploy to Code Engine** | Dockerfiles, build, secrets wiring, private networking, Cloud Logs, smoke test | 0, 5 |
| 7 | **Real providers** | Wire watsonx.ai / Tavily / PDL clients (James writes them; I host and supply credentials) | James |
| 8 | **Hardening** | SAST + dependency scan in CI, security unit tests, load check, runbook | all |

Frontend integration (Aanand) starts once phase 1 merges: he can build against the contract and sample responses.

## 6. Testing

- Unit tests with an in-memory repository fake; contract tests that validate API responses against OpenAPI and James's `check_brief_schema` shape.
- Integration tests against a real MongoDB (local `mongod` or a dev IBM instance, **[VERIFY]** which; test DB is separate from demo data).
- Security tests: cross-seller access returns 404, oversize/invalid CSV rejected, expired/forged JWT rejected, no PII in logs.
- Worker tests: lease expiry reclaim, duplicate enqueue, stale revision drop, max-attempt failure.

## 7. Security alignment (policy checklist)

- **Secrets:** env vars only, never committed; `.gitignore` already covers `.env*`. Rotation plan once Secrets Manager is adopted.
- **TLS:** HTTPS at the Code Engine edge; TLS 1.2+ to MongoDB with the service CA certificate verified (never disable validation). Outbound HTTPS with timeouts on every call.
- **Network:** MongoDB private endpoint preferred. **[VERIFY]** how Code Engine reaches a Databases private endpoint (VPE / project private visibility support). Fallback: public endpoint + TLS + IP allowlisting, documented as a risk.
- **Service binding:** bind to `127.0.0.1` by default (config via env var). **[VERIFY]** the Code Engine health check works that way. If it does not, I will stop and raise it with you instead of silently using `0.0.0.0` (policy forbids it).
- **Containers:** non-root `USER`, read-only root filesystem where possible, minimal Red Hat base image from `registry.redhat.io` (policy). **[VERIFY]** the current Python minimal UBI tag (we need Python 3.11+ per `apps/agents/pyproject.toml`) and how the build authenticates to `registry.redhat.io`. Image vulnerability scanning before deploy.
- **Dependencies:** latest stable, actively maintained only. For MongoDB use PyMongo's native async API; do **not** use Motor if it is end-of-life by implementation time **[VERIFY on PyPI at install]**. Commit lock files. Run dependency scanning (Mend per policy).
- **Input validation:** pydantic models with length/range limits equal to or stricter than the frontend (name 120, company/role 160, notes 4000, 50 lists, 1000 prospects). Parameterized/typed queries only; reject unknown fields.
- **Errors/logging:** generic client errors; structured JSON logs; no PII or secrets.

## 8. Mapping to James's open questions (my proposed answers)

| Q | Proposed answer |
|---|---|
| 2. Queue + worker owner | MongoDB `research_jobs` collection; Srikar owns deployment/queue, James owns code inside `run_research` |
| 3. Who writes the briefing | Worker writes it directly, conditional on `revision` |
| 4. Retries | Max 3 attempts, lease 90 s, exponential backoff |
| 7. Cache lifetime | 30 days, checked at enqueue and again in the worker |
| (60 s budget) | Accept 60 s per prospect as the agent timeout; lease 90 s |

## 9. Decisions I need from you before phase 0

1. **Database:** MongoDB Standard as proposed? (Or another store; Postgres is cheaper but conflicts with the team's NoSQL direction.)
2. **Free access scope:** which services and plans does the enterprise access cover (MongoDB, Code Engine, watsonx.ai plan, region)?
3. **"Seller cadence data":** what exactly is it (follow-up schedules? call history?) The README/handoff mention it but nothing defines it. It may need its own collection.
4. **Auth provider:** the diagram shows Supabase Auth, but Aanand's handoff says do not assume it. Which OIDC/SAML provider do we use? (Policy requires SAML or OpenID Connect.)
5. **Queue approach:** OK with the MongoDB-backed queue instead of RabbitMQ?
6. **Worker hosting:** OK with a Code Engine daemon job?
7. **Region** for all resources.
8. **Bob memory file:** add a short `AGENTS.md` that points to this plan? (Not yet decided; the plan itself is committed here.)

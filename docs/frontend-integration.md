# Frontend handoff — Lane D

## Current implementation

The complete frontend lives in `apps/web`. The main repository's backend, agent, and integration lanes are untouched. No backend API contract is established by the demo models.

This is a sample-data frontend. React screens consume `Prospect` and `Brief` data; `use-workspace.ts` owns demo persistence and simulated asynchronous research. This is the replacement point for backend integration, not a server implementation.

## Updated platform direction

The team has IBM Cloud access for the hackathon and plans to use an enterprise model there, plus a NoSQL database for seller cadence data. **Exact model/service and database remain open**, as requested. Do not assume Gemini, Supabase, PostgreSQL, or a particular IBM product. The frontend makes no direct calls to any model or database provider.

## Agreements needed with Lane C / Lane B

- Authentication and seller ownership checks; server persistence for lists, prospects, call sessions and notes.
- List/prospect CRUD, ordering, CSV import validation and duplicate semantics.
- Starting research and reading per-prospect progress, errors, retry state, and completed briefing.
- A versioned briefing payload linking each factual claim to evidence, with uncertainty and clear separation between source-supported facts, suggestions and seller notes.
- IBM model output normalization and evidence retention rules.
- Revision checks and idempotency: an older result cannot overwrite research for an edited prospect; retries cannot create duplicate call outcomes or records.
- Stable identifiers, timestamps, validation errors and pagination when dataset size exceeds demo limits.

Frontend research status and call status are independent. Call Connected displays already-held data immediately; it never triggers model work. Missing research still permits a notes-only calling view. All mutations need visible pending/error handling when moved to a real API.

## Removing the demo boundary

1. Agree the API and briefing examples with the affected owners.
2. Add an authenticated API client and query caching if needed. Replace the local reducer operations with server-backed operations and optimistic updates only where recoverable.
3. Replace the simulator with background-job status reads; preserve stale-result protection, retry states, and source-aware display.
4. Replace fictional evidence with validated source records and safe http/https links. Explicitly support live/sample mode rather than relabeling sample data as real.
5. Remove browser-local storage of prospect data once server persistence owns it. Keep only non-sensitive UI preferences locally.
6. Run the existing workflow tests against the integration and add ownership/authorization checks at the backend.

No auth UI, API keys, direct model calls, database schema, or production authorization behavior is implied by this frontend demo.

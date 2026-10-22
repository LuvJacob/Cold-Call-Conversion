# Cold Call Conversion frontend

Lane D's browser-local demo, built with Next.js, React, TypeScript, Radix Dialog, and a small token-based CSS system. The original Ugly MVP remains the interaction reference.

## Run

Use Node 22.13 or newer. From this directory:

```sh
npm ci
npm run dev
```

Open http://localhost:3000. For a production build, run `npm run build` then `npm start`.

## What works

- Create, rename, and remove calling lists.
- Add, edit, reorder, search, filter, and delete prospects.
- Import CSV files with previews, row errors, and duplicate detection. Required columns: `name`, `company`, `role` (or `title`); optional: `phone`, `notes`. Quoted commas, escaped quotes, BOM, and multiline notes are supported.
- Simulate research, inspect fictional evidence, see partial and failed states, and retry preparation.
- Browse overview, sources, and seller notes; browse prepared briefings across lists.
- Mark an external call connected, view notes and questions, save an outcome, and move to the next prospect. Active calls recover on reload.
- Persist in this browser's localStorage, with explicit warnings for unavailable or damaged storage. A stale tab pauses saving when another tab changes the workspace.
- Use the interface on narrow screens and with a keyboard; dialogs manage focus and brief tabs support arrow navigation.

All seed people/companies and research documents are fictional. The 555-01xx phone numbers are sample numbers. Research is a timer-based local simulation, not a network request. New or edited prospects receive general guidance and explicit unknowns; company facts are never fabricated from their names. Calling controls do not dial, record, listen, or transcribe.

The demo has no real sign-in or server persistence. localStorage is not suitable for confidential production data or multi-user collaboration. Clearing it removes the saved workspace. The app intentionally avoids a fake authentication screen.

## Verification

```sh
npm test
npm run typecheck
npm run build
npm run test:e2e
```

Browser tests use installed Chrome on macOS when present. Otherwise run `npx playwright install chromium` once. They start an isolated local dev server on port 3100; they do not use your regular browser profile.

## Integration boundary

See `docs/frontend-integration.md` at repository root. `src/lib/use-workspace.ts` owns local persistence and simulated preparation. `src/lib/model.ts` contains frontend-only models and state transitions. These are not an agreed backend API contract.

The project now targets an **IBM Cloud enterprise model** and a **NoSQL database**. The exact model service and database are intentionally unselected. There is no Gemini dependency, relational-database dependency, or model credential in this frontend. Replace the local data boundary with Lane C's agreed API and authentication when available.

## Limits

1,000 prospects and 50 lists per local demo workspace; imports are limited to 500 rows and 1 MB. Persistence is browser-local and intended for one active tab. No external services or paid resources are required to run the demo.

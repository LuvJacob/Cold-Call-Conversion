import { test } from "node:test";
import assert from "node:assert/strict";
import { parseProspectCsv } from "../src/lib/csv.ts";
import {
  createInitialState,
  reducer,
  restoreState,
  type WorkspaceState,
} from "../src/lib/model.ts";

test("CSV supports BOM, quoted commas, escaped quotes and multiline notes", () => {
  const result = parseProspectCsv(
    '\uFEFFName,Company,Title,Notes\r\n"Alex Chen","Acme, Inc.",CTO,"Said ""hello""\nand asked about costs"',
  );
  assert.equal(result.errors.length, 0);
  assert.equal(result.rows[0].company, "Acme, Inc.");
  assert.equal(result.rows[0].notes, 'Said "hello"\nand asked about costs');
});
test("CSV rejects missing required headers and malformed quoted values", () => {
  assert.ok(parseProspectCsv("name,company\nAlex,Acme").errors.length);
  assert.ok(
    parseProspectCsv('name,company,role\n"Alex,Acme,CTO').errors.length,
  );
  assert.ok(
    parseProspectCsv('name,company,role\n"Alex"oops,Acme,CTO').errors.length,
  );
});
test("CSV reports invalid rows without discarding valid rows", () => {
  const result = parseProspectCsv(
    "name,company,role\nAlex,Acme,CTO\n,Missing,CTO\nSam,Team,CEO,extra",
  );
  assert.equal(result.rows.length, 1);
  assert.equal(result.errors.length, 2);
});
test("CSV rejects ambiguous duplicate headers", () => {
  assert.ok(
    parseProspectCsv("name,full name,company,role\nAlex,Sam,Acme,CTO").errors
      .length,
  );
});
test("only one call can be active and ending it records the outcome", () => {
  let state = createInitialState();
  const [first, second] = state.prospects;
  state = reducer(state, {
    type: "connect",
    id: first.id,
    now: "2026-10-22T14:00:00Z",
  });
  state = reducer(state, {
    type: "connect",
    id: second.id,
    now: "2026-10-22T14:01:00Z",
  });
  assert.equal(state.activeCall?.prospectId, first.id);
  state = reducer(state, {
    type: "end-call",
    outcome: "follow-up",
    now: "2026-10-22T14:02:00Z",
  });
  assert.equal(state.activeCall, null);
  assert.equal(state.prospects[0].callStatus, "called");
  assert.equal(state.prospects[0].outcome, "follow-up");
  assert.equal(state.calls.length, 1);
});
test("editing a prospect invalidates research and ignores a stale result", () => {
  let state = createInitialState();
  const first = state.prospects[0];
  const brief = first.brief!;
  state = reducer(state, { type: "research-start", ids: [first.id] });
  state = reducer(state, {
    type: "save-prospect",
    prospect: {
      ...first,
      company: "Different company",
      notes: "  Keep these notes\nverbatim.  ",
    },
  });
  state = reducer(state, {
    type: "research-complete",
    id: first.id,
    revision: first.revision,
    brief,
  });
  assert.equal(state.prospects[0].researchStatus, "not-started");
  assert.equal(state.prospects[0].brief, null);
  assert.equal(state.prospects[0].notes, "  Keep these notes\nverbatim.  ");
});
test("an active prospect cannot be removed or edited", () => {
  let state = createInitialState();
  const first = state.prospects[0];
  state = reducer(state, {
    type: "connect",
    id: first.id,
    now: new Date().toISOString(),
  });
  state = reducer(state, { type: "delete-prospect", id: first.id });
  state = reducer(state, {
    type: "save-prospect",
    prospect: { ...first, name: "Changed" },
  });
  assert.equal(state.prospects[0].name, first.name);
});
test("import deduplicates within its list and within the same batch", () => {
  let state = createInitialState();
  const first = state.prospects[0];
  state = reducer(state, {
    type: "add-prospects",
    prospects: [
      { ...first, id: "duplicate-1" },
      { ...first, id: "duplicate-2" },
    ],
  });
  assert.equal(state.prospects.filter((p) => p.name === first.name).length, 1);
});
test("restoring interrupted research makes it retryable and preserves active calls", () => {
  let state = createInitialState();
  state = reducer(state, {
    type: "research-start",
    ids: [state.prospects[1].id],
  });
  state = reducer(state, {
    type: "connect",
    id: state.prospects[0].id,
    now: new Date().toISOString(),
  });
  const recovered = restoreState(JSON.stringify(state));
  assert.ok(recovered);
  assert.equal(recovered.prospects[1].researchStatus, "failed");
  assert.equal(recovered.activeCall?.prospectId, state.prospects[0].id);
});
test("invalid persisted data is rejected rather than trusted", () => {
  assert.equal(restoreState("{broken"), null);
  assert.equal(
    restoreState(JSON.stringify({ version: 1, prospects: [{}] })),
    null,
  );
  const state: WorkspaceState = createInitialState();
  state.prospects[0].listId = "missing-list";
  assert.equal(restoreState(JSON.stringify(state)), null);
});

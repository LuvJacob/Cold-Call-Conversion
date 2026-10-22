import { z } from "zod";
import { createSeedProspects } from "./sample-data.ts";

export const STORAGE_KEY = "cold-call-conversion:workspace:v1";
const id = z.string().min(1).max(100);
export const sourceSchema = z.object({
  id,
  title: z.string(),
  publisher: z.string(),
  excerpt: z.string(),
  url: z
    .string()
    .url()
    .regex(/^https?:\/\//)
    .nullable(),
});
export const briefSchema = z.object({
  mode: z.literal("demo"),
  preparedAt: z.string().datetime(),
  summary: z.string(),
  facts: z.array(
    z.object({
      label: z.string(),
      text: z.string(),
      sourceIds: z.array(z.string()),
    }),
  ),
  sources: z.array(sourceSchema),
  questions: z.array(z.object({ text: z.string(), basis: z.string() })),
  roleContext: z.string(),
  uncertainty: z.array(z.string()),
});
export type Brief = z.infer<typeof briefSchema>;
export const prospectInputSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a name.")
    .max(120, "Keep the name under 120 characters."),
  company: z.string().trim().min(1, "Enter a company.").max(160),
  role: z.string().trim().min(1, "Enter a job title.").max(160),
  phone: z.string().trim().max(80),
  notes: z.string().max(4000, "Keep notes under 4,000 characters."),
});
export type ProspectInput = z.infer<typeof prospectInputSchema>;
export const prospectSchema = prospectInputSchema.extend({
  id,
  listId: id,
  revision: z.number().int().nonnegative(),
  fixtureKey: z.string().nullable(),
  researchStatus: z.enum([
    "not-started",
    "running",
    "ready",
    "partial",
    "failed",
  ]),
  callStatus: z.enum(["ready", "called"]),
  outcome: z
    .enum(["completed", "follow-up", "not-interested", "no-answer"])
    .nullable(),
  brief: briefSchema.nullable(),
  researchError: z.string().nullable(),
});
export type Prospect = z.infer<typeof prospectSchema>;
export type ResearchStatus = Prospect["researchStatus"];
export type Outcome = NonNullable<Prospect["outcome"]>;
const activeCallSchema = z.object({
  prospectId: id,
  startedAt: z.string().datetime(),
});
export const workspaceSchema = z.object({
  version: z.literal(1),
  lists: z
    .array(z.object({ id, name: z.string().trim().min(1).max(80) }))
    .min(1)
    .max(50),
  prospects: z.array(prospectSchema).max(1000),
  activeCall: activeCallSchema.nullable(),
  calls: z
    .array(
      activeCallSchema.extend({
        endedAt: z.string().datetime(),
        outcome: z.enum([
          "completed",
          "follow-up",
          "not-interested",
          "no-answer",
        ]),
      }),
    )
    .max(10000),
});
export type WorkspaceState = z.infer<typeof workspaceSchema>;

export function createInitialState(): WorkspaceState {
  return {
    version: 1,
    lists: [
      { id: "list-outreach", name: "October outreach" },
      { id: "list-accounts", name: "Strategic accounts" },
    ],
    prospects: createSeedProspects(),
    activeCall: null,
    calls: [],
  };
}
export function makeProspect(input: ProspectInput, listId: string): Prospect {
  return {
    ...input,
    id: crypto.randomUUID(),
    listId,
    revision: 0,
    fixtureKey: null,
    researchStatus: "not-started",
    callStatus: "ready",
    outcome: null,
    brief: null,
    researchError: null,
  };
}
export function prospectKey(p: ProspectInput & { listId: string }) {
  return [p.listId, p.name, p.company, p.role]
    .map((v) => v.trim().toLocaleLowerCase())
    .join("\u001f");
}
export function restoreState(raw: string): WorkspaceState | null {
  try {
    const result = workspaceSchema.safeParse(JSON.parse(raw));
    if (!result.success) return null;
    const s = result.data;
    const listIds = new Set(s.lists.map((l) => l.id));
    const prospectIds = new Set(s.prospects.map((p) => p.id));
    if (
      listIds.size !== s.lists.length ||
      prospectIds.size !== s.prospects.length ||
      s.prospects.some((p) => !listIds.has(p.listId))
    )
      return null;
    if (s.activeCall && !prospectIds.has(s.activeCall.prospectId)) return null;
    return {
      ...s,
      prospects: s.prospects.map((p) =>
        p.researchStatus === "running"
          ? {
              ...p,
              researchStatus: "failed",
              researchError:
                "Preparation was interrupted. Try the demo research again.",
            }
          : p,
      ),
    };
  } catch {
    return null;
  }
}

export type Action =
  | { type: "hydrate"; state: WorkspaceState }
  | { type: "add-list"; id: string; name: string }
  | { type: "rename-list"; id: string; name: string }
  | { type: "delete-list"; id: string }
  | { type: "add-prospects"; prospects: Prospect[] }
  | { type: "save-prospect"; prospect: Prospect }
  | { type: "delete-prospect"; id: string }
  | { type: "move"; id: string; direction: -1 | 1 }
  | { type: "research-start"; ids: string[] }
  | { type: "research-complete"; id: string; revision: number; brief: Brief }
  | { type: "research-failed"; id: string; revision: number; error: string }
  | { type: "connect"; id: string; now: string }
  | { type: "end-call"; outcome: Outcome; now: string }
  | { type: "reset-call"; id: string }
  | { type: "reset" };

export function reducer(state: WorkspaceState, action: Action): WorkspaceState {
  switch (action.type) {
    case "hydrate":
      return action.state;
    case "reset":
      return createInitialState();
    case "add-list":
      if (!action.name.trim() || state.lists.length >= 50) return state;
      return {
        ...state,
        lists: [
          ...state.lists,
          { id: action.id, name: action.name.trim().slice(0, 80) },
        ],
      };
    case "rename-list":
      if (!action.name.trim()) return state;
      return {
        ...state,
        lists: state.lists.map((l) =>
          l.id === action.id
            ? { ...l, name: action.name.trim().slice(0, 80) }
            : l,
        ),
      };
    case "delete-list": {
      if (
        state.lists.length === 1 ||
        state.prospects.some(
          (p) =>
            p.listId === action.id && p.id === state.activeCall?.prospectId,
        )
      )
        return state;
      const deleted = new Set(
        state.prospects.filter((p) => p.listId === action.id).map((p) => p.id),
      );
      return {
        ...state,
        lists: state.lists.filter((l) => l.id !== action.id),
        prospects: state.prospects.filter((p) => !deleted.has(p.id)),
        calls: state.calls.filter((c) => !deleted.has(c.prospectId)),
      };
    }
    case "add-prospects": {
      const keys = new Set(state.prospects.map(prospectKey));
      const existingIds = new Set(state.prospects.map((p) => p.id));
      const additions = action.prospects.filter((p) => {
        const key = prospectKey(p);
        if (
          keys.has(key) ||
          existingIds.has(p.id) ||
          !state.lists.some((l) => l.id === p.listId)
        )
          return false;
        keys.add(key);
        existingIds.add(p.id);
        return true;
      });
      return {
        ...state,
        prospects: [...state.prospects, ...additions].slice(0, 1000),
      };
    }
    case "save-prospect":
      if (state.activeCall?.prospectId === action.prospect.id) return state;
      return {
        ...state,
        prospects: state.prospects.map((p) =>
          p.id === action.prospect.id
            ? {
                ...p,
                ...prospectInputSchema.parse(action.prospect),
                revision: p.revision + 1,
                fixtureKey: null,
                brief: null,
                researchStatus: "not-started",
                researchError: null,
              }
            : p,
        ),
      };
    case "delete-prospect":
      if (state.activeCall?.prospectId === action.id) return state;
      return {
        ...state,
        prospects: state.prospects.filter((p) => p.id !== action.id),
        calls: state.calls.filter((c) => c.prospectId !== action.id),
      };
    case "move": {
      const index = state.prospects.findIndex((p) => p.id === action.id);
      if (index < 0) return state;
      const list = state.prospects.filter(
        (p) => p.listId === state.prospects[index].listId,
      );
      const next =
        list[list.findIndex((p) => p.id === action.id) + action.direction];
      if (!next) return state;
      const other = state.prospects.findIndex((p) => p.id === next.id);
      const prospects = [...state.prospects];
      [prospects[index], prospects[other]] = [
        prospects[other],
        prospects[index],
      ];
      return { ...state, prospects };
    }
    case "research-start":
      return {
        ...state,
        prospects: state.prospects.map((p) =>
          action.ids.includes(p.id) &&
          p.researchStatus !== "running" &&
          p.id !== state.activeCall?.prospectId
            ? { ...p, researchStatus: "running", researchError: null }
            : p,
        ),
      };
    case "research-complete":
      return {
        ...state,
        prospects: state.prospects.map((p) =>
          p.id === action.id &&
          p.revision === action.revision &&
          p.researchStatus === "running"
            ? {
                ...p,
                brief: action.brief,
                researchStatus: action.brief.uncertainty.length
                  ? "partial"
                  : "ready",
                researchError: null,
              }
            : p,
        ),
      };
    case "research-failed":
      return {
        ...state,
        prospects: state.prospects.map((p) =>
          p.id === action.id &&
          p.revision === action.revision &&
          p.researchStatus === "running"
            ? { ...p, researchStatus: "failed", researchError: action.error }
            : p,
        ),
      };
    case "connect":
      if (state.activeCall || !state.prospects.some((p) => p.id === action.id))
        return state;
      return {
        ...state,
        activeCall: { prospectId: action.id, startedAt: action.now },
      };
    case "end-call": {
      if (!state.activeCall) return state;
      const call = state.activeCall;
      return {
        ...state,
        activeCall: null,
        calls: [
          ...state.calls,
          { ...call, endedAt: action.now, outcome: action.outcome },
        ].slice(-10000),
        prospects: state.prospects.map((p) =>
          p.id === call.prospectId
            ? { ...p, callStatus: "called", outcome: action.outcome }
            : p,
        ),
      };
    }
    case "reset-call":
      return {
        ...state,
        prospects: state.prospects.map((p) =>
          p.id === action.id && p.id !== state.activeCall?.prospectId
            ? { ...p, callStatus: "ready", outcome: null }
            : p,
        ),
      };
  }
}

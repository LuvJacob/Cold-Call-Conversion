"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, ApiError } from "./api";
import {
  reducer,
  type Action,
  type ProspectInput,
  type WorkspaceState,
} from "./model";

export const POLL_MS = 2500;

const emptyState = (): WorkspaceState => ({
  version: 1,
  lists: [{ id: "loading", name: "Loading…" }],
  prospects: [],
  activeCall: null,
  calls: [],
});
const message = (e: unknown) =>
  e instanceof ApiError
    ? e.message
    : "Something went wrong talking to the server.";

// API mode: the server owns lists, prospects, calls and research. The reducer
// is only used for optimistic updates; every mutation is followed by a refresh
// of the authoritative workspace, so a failed call heals itself.
export function useApiWorkspace() {
  const [state, rawDispatch] = useReducer(reducer, undefined, emptyState);
  const [loaded, setLoaded] = useState(false);
  const [warning, setWarning] = useState("");
  const alive = useRef(true);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const stateRef = useRef(state);
  stateRef.current = state;
  const polling = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const next = await api.workspace();
      if (alive.current) {
        rawDispatch({ type: "hydrate", state: next });
        setWarning("");
      }
    } catch (e) {
      if (alive.current)
        setWarning(`${message(e)} Showing the last data loaded.`);
    } finally {
      if (alive.current) setLoaded(true);
    }
  }, []);

  // Mutations run one at a time so edits cannot overtake each other.
  const run = useCallback(
    <T>(task: () => Promise<T>): Promise<T | null> => {
      const result = queue.current.then(async () => {
        try {
          const value = await task();
          await refresh();
          return value;
        } catch (e) {
          if (alive.current) setWarning(message(e));
          await refresh();
          // refresh() clears the warning on success; show the error again.
          if (alive.current) setWarning(message(e));
          return null;
        }
      });
      queue.current = result.catch(() => null);
      return result;
    },
    [refresh],
  );

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  // Poll research for running prospects until they settle. Stops on unmount
  // and when nothing is running.
  const anyRunning = state.prospects.some(
    (p) => p.researchStatus === "running",
  );
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        const running = stateRef.current.prospects.filter(
          (p) => p.researchStatus === "running",
        );
        const results = await Promise.all(
          running.map((p) => api.researchStatus(p.id).catch(() => null)),
        );
        const settled = results.some(
          (r, i) =>
            r &&
            (r.revision !== running[i].revision ||
              !["queued", "running", "not-started"].includes(r.researchStatus)),
        );
        if (settled && alive.current) await refresh();
      } finally {
        polling.current = false;
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [anyRunning, refresh]);

  const dispatch = useCallback(
    (action: Action) => {
      switch (action.type) {
        case "research-start": {
          const ids = action.ids.filter((id) => {
            const p = stateRef.current.prospects.find((x) => x.id === id);
            return (
              p &&
              p.researchStatus !== "running" &&
              id !== stateRef.current.activeCall?.prospectId
            );
          });
          if (!ids.length) return;
          rawDispatch({ type: "research-start", ids });
          void run(() => api.startResearch(ids));
          return;
        }
        case "save-prospect": {
          const p = action.prospect;
          rawDispatch(action);
          void run(() => api.updateProspect(p.id, p));
          return;
        }
        case "delete-prospect":
          rawDispatch(action);
          void run(() => api.deleteProspect(action.id));
          return;
        case "move":
          rawDispatch(action);
          void run(() => api.moveProspect(action.id, action.direction));
          return;
        case "rename-list":
          rawDispatch(action);
          void run(() => api.renameList(action.id, action.name));
          return;
        case "delete-list":
          rawDispatch(action);
          void run(() => api.deleteList(action.id));
          return;
        case "connect":
          rawDispatch(action);
          void run(() => api.connect(action.id));
          return;
        case "end-call":
          rawDispatch(action);
          void run(() => api.endCall(action.outcome));
          return;
        case "reset-call":
          rawDispatch(action);
          void run(() => api.resetCall(action.id));
          return;
        case "add-prospects": {
          const byList = new Map<string, ProspectInput[]>();
          for (const p of action.prospects)
            byList.set(p.listId, [...(byList.get(p.listId) ?? []), p]);
          for (const [listId, inputs] of byList)
            void run(() => api.createProspects(listId, inputs));
          return;
        }
        default:
          // add-list is handled by createList; hydrate/reset do not apply.
          return;
      }
    },
    [run],
  );

  const createList = useCallback(
    async (name: string) => (await run(() => api.createList(name)))?.id ?? null,
    [run],
  );
  const createProspects = useCallback(
    async (listId: string, inputs: ProspectInput[]) =>
      (await run(() => api.createProspects(listId, inputs))) ?? [],
    [run],
  );

  const importCsv = useCallback(
    async (listId: string, file: File) =>
      await run(() => api.importCsv(listId, file)),
    [run],
  );

  return {
    mode: "api" as const,
    state,
    dispatch,
    loaded,
    storageWarning: warning,
    storageConflict: false,
    savingAllowed: true,
    reset: () => {},
    retrySave: () => void refresh(),
    createList,
    createProspects,
    importCsv,
  };
}

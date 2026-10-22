"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import {
  createInitialState,
  reducer,
  restoreState,
  STORAGE_KEY,
} from "./model";
import { createDemoBrief } from "./sample-data";

// Lane D demo boundary: replace storage and this simulator with Lane C's
// agreed API. Screen components never call an AI provider directly.
export function useWorkspace() {
  const [state, dispatch] = useReducer(reducer, undefined, createInitialState);
  const [loaded, setLoaded] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  const [savingAllowed, setSavingAllowed] = useState(true);
  const [saveAttempt, setSaveAttempt] = useState(0);
  const [storageConflict, setStorageConflict] = useState(false);
  const lastSaved = useRef<string | null>(null);
  const lastState = useRef<string | null>(null);
  const conflict = useRef(false);
  const jobs = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      lastSaved.current = raw;
      if (raw) {
        const restored = restoreState(raw);
        if (restored) {
          lastState.current = JSON.stringify(restored);
          dispatch({ type: "hydrate", state: restored });
        } else {
          setSavingAllowed(false);
          setStorageWarning(
            "Saved data could not be read. It has not been overwritten. This session uses sample data; reset the demo to start saving again.",
          );
        }
      }
    } catch {
      setStorageWarning(
        "Browser storage is unavailable. Changes will last only for this session.",
      );
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (
        (event.key === STORAGE_KEY || event.key === null) &&
        event.newValue !== lastSaved.current
      ) {
        conflict.current = true;
        setStorageConflict(true);
        setStorageWarning(
          "This workspace changed in another tab. Saving here is paused to protect the newer data. Reloading discards this tab’s unsaved changes and opens the latest saved version.",
        );
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (!loaded || !savingAllowed || conflict.current) return;
    try {
      const current = localStorage.getItem(STORAGE_KEY);
      const next = JSON.stringify(state);
      // Merely opening another tab must not rewrite an equivalent parsed snapshot.
      if (next === lastState.current && saveAttempt === 0) return;
      if (current !== lastSaved.current && current !== next) {
        conflict.current = true;
        setStorageConflict(true);
        setStorageWarning(
          "This workspace changed in another tab. Saving here is paused to protect the newer data. Reloading discards this tab’s unsaved changes and opens the latest saved version.",
        );
        return;
      }
      localStorage.setItem(STORAGE_KEY, next);
      lastSaved.current = next;
      lastState.current = next;
      setStorageWarning("");
    } catch {
      setStorageWarning(
        "Your latest changes could not be saved in this browser. Keep this tab open and retry saving.",
      );
    }
  }, [state, loaded, savingAllowed, saveAttempt]);

  useEffect(() => {
    if (!loaded) return;
    for (const p of state.prospects) {
      const key = `${p.id}:${p.revision}`;
      if (p.researchStatus !== "running" || jobs.current.has(key)) continue;
      const timer = setTimeout(() => {
        try {
          dispatch({
            type: "research-complete",
            id: p.id,
            revision: p.revision,
            brief: createDemoBrief(p),
          });
        } catch {
          dispatch({
            type: "research-failed",
            id: p.id,
            revision: p.revision,
            error: "The sample brief could not be prepared. Please retry.",
          });
        }
        jobs.current.delete(key);
      }, 2200);
      jobs.current.set(key, timer);
    }
    for (const [key, timer] of jobs.current) {
      if (
        !state.prospects.some(
          (p) =>
            `${p.id}:${p.revision}` === key && p.researchStatus === "running",
        )
      ) {
        clearTimeout(timer);
        jobs.current.delete(key);
      }
    }
  }, [loaded, state.prospects]);

  useEffect(() => {
    const timers = jobs.current;
    return () => {
      timers.forEach(clearTimeout);
      timers.clear();
    };
  }, []);

  const reset = () => {
    jobs.current.forEach(clearTimeout);
    jobs.current.clear();
    try {
      lastSaved.current = localStorage.getItem(STORAGE_KEY);
    } catch {
      /* The save effect reports unavailable storage. */
    }
    conflict.current = false;
    setStorageConflict(false);
    setSavingAllowed(true);
    dispatch({ type: "reset" });
  };
  return {
    state,
    dispatch,
    loaded,
    storageWarning,
    storageConflict,
    savingAllowed,
    reset,
    retrySave: () => setSaveAttempt((n) => n + 1),
  };
}

// Pure logic for the optional live transcript. Uses the browser's Web Speech
// API only; nothing is sent to our backend or stored.
import type { Brief } from "./model.ts";

export type RecognitionResultLike = {
  isFinal: boolean;
  0: { transcript: string };
};
export type RecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<RecognitionResultLike>;
};
export type RecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: RecognitionEventLike) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
};
export type RecognitionCtor = new () => RecognitionLike;

export function getRecognitionCtor(
  win: unknown = typeof window === "undefined" ? undefined : window,
): RecognitionCtor | null {
  const w = win as
    | {
        SpeechRecognition?: RecognitionCtor;
        webkitSpeechRecognition?: RecognitionCtor;
      }
    | undefined;
  return w?.SpeechRecognition ?? w?.webkitSpeechRecognition ?? null;
}
export const isTranscriptSupported = (win?: unknown) =>
  getRecognitionCtor(win) !== null;

export function friendlyError(code?: string): string {
  if (code === "not-allowed" || code === "service-not-allowed")
    return "Microphone access was blocked. Allow the microphone in your browser to use live transcript.";
  if (code === "audio-capture")
    return "No microphone was found. Check your audio input and try again.";
  if (code === "network")
    return "Speech service unreachable. Check your connection and start again.";
  return "Live transcript hit a problem and stopped. You can start it again.";
}

const FATAL = new Set([
  "not-allowed",
  "service-not-allowed",
  "audio-capture",
  "network",
]);
const MAX_QUICK_RESTARTS = 3;
const QUICK_MS = 2000;

export type TranscriptHandlers = {
  onFinal: (text: string) => void;
  onInterim: (text: string) => void;
  onError: (message: string) => void;
  onStop?: () => void;
};

/** Starts recognition; restarts on end while listening. Returns a stop function. */
export function startTranscription(
  Ctor: RecognitionCtor,
  h: TranscriptHandlers,
): () => void {
  let listening = true;
  let rec: RecognitionLike | undefined;
  let startedAt = 0;
  let quickRestarts = 0;
  const launch = () => {
    const r = new Ctor();
    rec = r;
    startedAt = Date.now();
    r.continuous = true;
    r.interimResults = true;
    r.lang = "en-US";
    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const t = res[0].transcript.trim();
        if (res.isFinal) {
          if (t) h.onFinal(t);
        } else interim += (interim ? " " : "") + t;
      }
      h.onInterim(interim);
    };
    r.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error && FATAL.has(e.error)) listening = false;
      h.onError(friendlyError(e.error));
    };
    r.onend = () => {
      if (!listening) {
        h.onStop?.();
        return;
      }
      quickRestarts = Date.now() - startedAt < QUICK_MS ? quickRestarts + 1 : 0;
      if (quickRestarts > MAX_QUICK_RESTARTS) {
        listening = false;
        h.onError(
          "Live transcript keeps stopping, so it was turned off. Start it again when ready.",
        );
        h.onStop?.();
        return;
      }
      try {
        launch();
      } catch {
        listening = false;
        h.onError(friendlyError());
        h.onStop?.();
      }
    };
    r.start();
  };
  try {
    launch();
  } catch {
    listening = false;
    h.onError(friendlyError());
    h.onStop?.();
  }
  return () => {
    if (!listening) return;
    listening = false;
    h.onInterim("");
    try {
      rec?.stop();
    } catch {
      /* already stopped */
    }
  };
}

export type Cue = { trigger: string; hint: string };

export const SALES_TRIGGERS = [
  "budget",
  "pricing",
  "cost",
  "timeline",
  "competitor",
  "contract",
  "renewal",
  "decision",
  "security",
  "integration",
  "headcount",
  "hiring",
  "expansion",
];
const STOP = new Set(
  "the a an and or of to in on for with is are was were be at by from that this it as their they your our we you not but has have had will can who what when how more than into over about".split(
    " ",
  ),
);
const words = (s: string) =>
  s
    .toLowerCase()
    .match(/[a-z0-9]{4,}/g)
    ?.filter((w) => !STOP.has(w)) ?? [];

/** Deterministic keyword matching; returns up to `max` cues. */
export function findCues(
  text: string,
  brief: Brief | null | undefined,
  max = 3,
): Cue[] {
  const spoken = new Set(words(text));
  if (!spoken.size) return [];
  const cues: Cue[] = [];
  const seen = new Set<string>();
  const add = (word: string, hint: string) => {
    if (cues.length < max && !seen.has(hint)) {
      seen.add(hint);
      cues.push({ trigger: word, hint });
    }
  };
  const questions = brief?.questions ?? [];
  const facts = brief?.facts ?? [];
  const hit = (s: string, w: string) => words(s).includes(w);
  for (const w of SALES_TRIGGERS) {
    if (!spoken.has(w)) continue;
    const q = questions.find((x) => hit(x.text, w));
    const f = facts.find((x) => hit(`${x.label} ${x.text}`, w));
    if (q) add(w, `Suggested question: ${q.text}`);
    else if (f) add(w, `Related fact: ${f.label}: ${f.text}`);
    else add(w, `Ask about their ${w}.`);
  }
  for (const w of spoken) {
    if (SALES_TRIGGERS.includes(w)) continue;
    const q = questions.find((x) => hit(x.text, w));
    if (q) add(w, `Suggested question: ${q.text}`);
    else {
      const f = facts.find((x) => hit(`${x.label} ${x.text}`, w));
      if (f) add(w, `Related fact: ${f.label}: ${f.text}`);
    }
  }
  return cues;
}

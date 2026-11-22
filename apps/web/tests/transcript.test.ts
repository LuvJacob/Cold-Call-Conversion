import { test } from "node:test";
import assert from "node:assert/strict";
import {
  findCues,
  getRecognitionCtor,
  isTranscriptSupported,
  startTranscription,
  type RecognitionLike,
} from "../src/lib/transcript.ts";
import type { Brief } from "../src/lib/model.ts";

const brief = {
  mode: "demo",
  preparedAt: new Date().toISOString(),
  summary: "",
  facts: [{ label: "Headcount", text: "About 200 engineers", sourceIds: [] }],
  sources: [],
  questions: [{ text: "How do you plan your pricing review?", basis: "" }],
  roleContext: "",
  uncertainty: [],
} as Brief;

test("feature detection", () => {
  assert.equal(isTranscriptSupported({}), false);
  assert.equal(isTranscriptSupported(undefined), false);
  class R {}
  assert.equal(getRecognitionCtor({ webkitSpeechRecognition: R }), R);
  assert.equal(isTranscriptSupported({ SpeechRecognition: R }), true);
});

test("findCues matches triggers and brief words, max 3", () => {
  const c = findCues("What about pricing and headcount?", brief);
  assert.equal(c[0].trigger, "pricing");
  assert.match(c[0].hint, /Suggested question: How do you plan/);
  assert.match(c[1].hint, /Related fact: Headcount/);
  assert.deepEqual(findCues("hello there", brief), []);
  assert.equal(
    findCues("budget timeline competitor contract renewal", null).length,
    3,
  );
  assert.deepEqual(findCues("budget", null), [
    { trigger: "budget", hint: "Ask about their budget." },
  ]);
});

function fake() {
  const instances: (RecognitionLike & { started: number; stopped: number })[] =
    [];
  class Fake {
    continuous = false;
    interimResults = false;
    lang = "";
    onresult: RecognitionLike["onresult"] = null;
    onerror: RecognitionLike["onerror"] = null;
    onend: RecognitionLike["onend"] = null;
    started = 0;
    stopped = 0;
    constructor() {
      instances.push(this);
    }
    start() {
      this.started++;
    }
    stop() {
      this.stopped++;
    }
  }
  return { Fake, instances };
}

test("wrapper emits results, restarts on end, stops cleanly", () => {
  const { Fake, instances } = fake();
  const finals: string[] = [];
  const interims: string[] = [];
  const stop = startTranscription(Fake, {
    onFinal: (t) => finals.push(t),
    onInterim: (t) => interims.push(t),
    onError: () => assert.fail("no error"),
  });
  const a = instances[0];
  assert.equal(a.lang, "en-US");
  assert.ok(a.continuous && a.interimResults);
  a.onresult?.({
    resultIndex: 0,
    results: [
      { isFinal: true, 0: { transcript: " hello " } },
      { isFinal: false, 0: { transcript: "wor" } },
    ],
  });
  assert.deepEqual(finals, ["hello"]);
  assert.equal(interims.at(-1), "wor");
  a.onend?.();
  assert.equal(instances.length, 2);
  assert.equal(instances[1].started, 1);
  stop();
  assert.equal(instances[1].stopped, 1);
  instances[1].onend?.();
  assert.equal(instances.length, 2);
});

test("permission denied reports a friendly error and does not restart", () => {
  const { Fake, instances } = fake();
  const errors: string[] = [];
  startTranscription(Fake, {
    onFinal: () => {},
    onInterim: () => {},
    onError: (m) => errors.push(m),
  });
  instances[0].onerror?.({ error: "not-allowed" });
  instances[0].onend?.();
  assert.match(errors[0], /Microphone access was blocked/);
  assert.equal(instances.length, 1);
});

test("network error is fatal with a clear message", () => {
  const { Fake, instances } = fake();
  const errors: string[] = [];
  startTranscription(Fake, {
    onFinal: () => {},
    onInterim: () => {},
    onError: (m) => errors.push(m),
  });
  instances[0].onerror?.({ error: "network" });
  instances[0].onend?.();
  assert.match(errors[0], /Speech service unreachable/);
  assert.equal(instances.length, 1);
});

test("stops after 3 rapid consecutive restarts", () => {
  const { Fake, instances } = fake();
  const errors: string[] = [];
  let stopped = 0;
  startTranscription(Fake, {
    onFinal: () => {},
    onInterim: () => {},
    onError: (m) => errors.push(m),
    onStop: () => stopped++,
  });
  for (let i = 0; i < 4; i++) instances[i]?.onend?.();
  assert.equal(instances.length, 4);
  assert.equal(stopped, 1);
  assert.match(errors[0], /keeps stopping/);
});

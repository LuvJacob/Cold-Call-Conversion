"use client";

import { useEffect, useRef, useState } from "react";
import type { Brief } from "@/lib/model";
import {
  findCues,
  getRecognitionCtor,
  startTranscription,
  type RecognitionCtor,
} from "@/lib/transcript";

export function LiveTranscript({
  brief,
}: {
  brief: Brief | null;
}) {
  const [ctor, setCtor] = useState<RecognitionCtor | null | undefined>();
  const [consent, setConsent] = useState(false);
  const [listening, setListening] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const stopRef = useRef<(() => void) | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const c = getRecognitionCtor();
    setCtor(() => c); // wrap: a constructor passed directly is treated as an updater
    return () => stopRef.current?.();
  }, []);
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight });
  }, [lines, interim]);

  function start() {
    if (!ctor) return;
    setError("");
    setStatus("");
    setListening(true);
    stopRef.current = startTranscription(ctor, {
      onFinal: (t) => setLines((l) => [...l, t]),
      onInterim: setInterim,
      onError: setError,
      onStop: () => {
        setListening(false);
        stopRef.current = null;
      },
    });
  }
  function stop() {
    stopRef.current?.();
    stopRef.current = null;
    setListening(false);
  }
  const full = lines.join("\n");
  const cues = findCues(lines.slice(-3).join(" "), brief);

  return (
    <section className="live-transcript" aria-label="Live transcript">
      <h2>Live transcript</h2>
      {ctor === undefined ? null : ctor === null ? (
        <p className="muted">Live transcript needs Chrome or Edge</p>
      ) : (
        <>
          <label>
            <input
              type="checkbox"
              checked={consent}
              disabled={listening}
              onChange={(e) => setConsent(e.target.checked)}
            />{" "}
            I&apos;ve told the other person this call may be transcribed.
          </label>
          <div>
            {listening ? (
              <>
                <strong role="status" style={{ color: "#c62828" }}>
                  ● Listening
                </strong>{" "}
                <button type="button" onClick={stop}>
                  Stop
                </button>
              </>
            ) : (
              <button type="button" disabled={!consent} onClick={start}>
                Start listening
              </button>
            )}
          </div>
          {error && <p role="alert">{error}</p>}
          <div
            ref={box}
            aria-live="polite"
            style={{ maxHeight: 160, overflowY: "auto" }}
          >
            {lines.map((l, i) => (
              <p key={i}>{l}</p>
            ))}
            {interim && <p className="muted">{interim}</p>}
          </div>
          {cues.length > 0 && (
            <ul aria-label="Conversation cues">
              {cues.map((c) => (
                <li key={c.hint}>
                  They mentioned {c.trigger} → {c.hint}
                </li>
              ))}
            </ul>
          )}
          {!listening && full && (
            <div>
              <button
                type="button"
                onClick={() => {
                  const fail = () =>
                    setStatus(
                      "Couldn't copy. Select the text above and copy it manually.",
                    );
                  if (!navigator.clipboard?.writeText) return fail();
                  navigator.clipboard
                    .writeText(full)
                    .then(() => setStatus("Copied"), fail);
                }}
              >
                Copy transcript
              </button>
              <span role="status"> {status}</span>
            </div>
          )}
          <p className="muted" style={{ fontSize: 12 }}>
            Transcribed by your browser&apos;s speech service. Audio isn&apos;t
            saved; the transcript stays on this screen.
          </p>
        </>
      )}
    </section>
  );
}

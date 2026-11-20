"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PictureInPicture2 } from "lucide-react";
import type { Prospect } from "@/lib/model";
import { Button } from "./ui";
import {
  copyStyles,
  isPopoutSupported,
  openPopout,
  POPOUT_UNSUPPORTED_TIP,
} from "./popout-window";

function PopoutContent({
  prospect,
  openLink,
}: {
  prospect: Prospect;
  openLink: (url: string) => void;
}) {
  const brief = prospect.brief;
  if (!brief) return null;
  const sourceById = new Map(brief.sources.map((s) => [s.id, s]));
  return (
    <div
      className="brief-overview"
      style={{ padding: 16, overflowY: "auto", height: "100vh" }}
    >
      <span className="company-kicker">{prospect.company}</span>
      <h2>{prospect.name}</h2>
      <p className="company-summary">{brief.summary}</p>
      <section className="brief-section">
        <h3>Key facts</h3>
        <div className="fact-list">
          {brief.facts.map((fact) => (
            <div className="fact" key={fact.label}>
              <div>
                <h4>{fact.label}</h4>
                <p>{fact.text}</p>
                {fact.sourceIds.map((id) => {
                  const s = sourceById.get(id);
                  if (!s) return null;
                  return s.url && /^https?:\/\//.test(s.url) ? (
                    <a
                      key={id}
                      className="text-link"
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => {
                        e.preventDefault();
                        openLink(s.url as string);
                      }}
                    >
                      {s.title}{" "}
                    </a>
                  ) : (
                    <small key={id}>{s.title} </small>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="brief-section">
        <h3>Questions</h3>
        <ol className="question-list">
          {brief.questions.map((q) => (
            <li key={q.text}>
              <div>
                <p>{q.text}</p>
                <small>{q.basis}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>
      {!!brief.uncertainty.length && (
        <div className="callout">
          <div>
            <strong>Uncertain</strong>
            <ul>
              {brief.uncertainty.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export function BriefingPopout({ prospect }: { prospect: Prospect }) {
  const [pip, setPip] = useState<Window | null>(null);
  const pipRef = useRef<Window | null>(null);
  const [supported, setSupported] = useState(false);
  useEffect(() => setSupported(isPopoutSupported(window)), []);

  const close = useCallback(() => {
    const w = pipRef.current;
    pipRef.current = null;
    setPip(null);
    if (w && !w.closed) w.close();
  }, []);

  // One window at a time, tied to the current prospect and this component.
  useEffect(() => close, [prospect.id, close]);

  if (!prospect.brief) return null;

  const onClick = async () => {
    if (pipRef.current && !pipRef.current.closed) {
      pipRef.current.focus();
      return;
    }
    try {
      const w = await openPopout(window);
      if (!w) return;
      copyStyles(document, w.document);
      w.document.title = `${prospect.name} briefing`;
      w.addEventListener("pagehide", () => {
        if (pipRef.current === w) {
          pipRef.current = null;
          setPip(null);
        }
      });
      pipRef.current = w;
      setPip(w);
    } catch {
      /* user dismissed or the browser refused; leave the button usable */
    }
  };

  return (
    <>
      <Button
        variant="secondary"
        small
        onClick={onClick}
        disabled={!supported}
        aria-label={
          supported
            ? "Pop out briefing in a floating window"
            : POPOUT_UNSUPPORTED_TIP
        }
        title={supported ? "Pop out briefing" : POPOUT_UNSUPPORTED_TIP}
      >
        <PictureInPicture2 size={14} />
        Pop out briefing
      </Button>
      {pip &&
        createPortal(
          <PopoutContent
            prospect={prospect}
            openLink={(url) => window.open(url, "_blank", "noopener,noreferrer")}
          />,
          pip.document.body,
        )}
    </>
  );
}

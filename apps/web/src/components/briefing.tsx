"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Building2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  Copy,
  FileText,
  Lightbulb,
  Pencil,
  Phone,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import type { Brief, Outcome, Prospect } from "@/lib/model";
import { Avatar, Button, EmptyState, IconButton, ResearchBadge } from "./ui";

export function BriefOverview({
  prospect,
  onSources,
  onEdit,
  onResearch,
  onRetry,
}: {
  prospect: Prospect;
  onSources?: () => void;
  onEdit?: () => void;
  onResearch?: () => void;
  onRetry?: () => void;
}) {
  const brief = prospect.brief;
  return (
    <div className="brief-overview">
      {prospect.researchStatus === "running" && (
        <div className="preparation-progress" role="status">
          <RefreshCw size={16} className="spin" />
          <div>
            <strong>Preparing a sample briefing</strong>
            <span>
              Simulated research. No external sources are being contacted.
            </span>
          </div>
        </div>
      )}
      {prospect.researchStatus === "failed" && (
        <div className="callout callout-error">
          <CircleAlert size={17} />
          <div>
            <strong>Preparation needs another try</strong>
            <p>{prospect.researchError}</p>
            {onRetry && (
              <button className="text-link" onClick={onRetry}>
                Retry demo research <ArrowRight size={13} />
              </button>
            )}
          </div>
        </div>
      )}
      {brief ? (
        <>
          <section className="brief-section">
            <div className="section-label">
              <Building2 size={15} />
              <h3>The company, in context</h3>
              <span className="tiny-label">Sample</span>
            </div>
            <p className="company-summary">{brief.summary}</p>
            <div className="fact-list">
              {brief.facts.map((fact, index) => (
                <div className="fact" key={fact.label}>
                  <span className="fact-number">0{index + 1}</span>
                  <div>
                    <h4>{fact.label}</h4>
                    <p>{fact.text}</p>
                    {onSources && (
                      <button className="source-reference" onClick={onSources}>
                        <FileText size={11} />
                        Demo source{fact.sourceIds.length > 1 ? "s" : ""}{" "}
                        {fact.sourceIds
                          .map(
                            (id) =>
                              brief.sources.findIndex((s) => s.id === id) + 1,
                          )
                          .join(", ")}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
          {!!brief.uncertainty.length && (
            <div className="callout">
              <CircleAlert size={17} />
              <div>
                <strong>A little more context is needed</strong>
                <ul>
                  {brief.uncertainty.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      ) : prospect.researchStatus !== "running" &&
        prospect.researchStatus !== "failed" ? (
        <div className="unprepared">
          <Search size={24} strokeWidth={1.5} />
          <h3>A little research goes a long way.</h3>
          <p>
            Prepare a sample briefing to explore the workflow. Your notes are
            available right now.
          </p>
          {onResearch && (
            <Button variant="secondary" small onClick={onResearch}>
              <RefreshCw size={14} />
              Prepare sample brief
            </Button>
          )}
        </div>
      ) : null}
      <section className="brief-section notes-section">
        <div className="section-label">
          <FileText size={15} />
          <h3>Your notes</h3>
          <span className="tiny-label">Seller-provided</span>
          {onEdit && (
            <IconButton label="Edit seller notes" onClick={onEdit}>
              <Pencil size={13} />
            </IconButton>
          )}
        </div>
        <p className={prospect.notes ? "seller-notes" : "empty-notes"}>
          {prospect.notes ||
            "No notes yet. Add a previous conversation, a referral, or something you want to ask."}
        </p>
      </section>
      {brief && (
        <>
          <section className="brief-section">
            <div className="section-label">
              <Lightbulb size={15} />
              <h3>Open the conversation</h3>
              <span className="tiny-label">Suggestions</span>
            </div>
            <QuestionList brief={brief} />
          </section>
          <section className="brief-section role-section">
            <div className="section-label">
              <BookOpen size={15} />
              <h3>About the role</h3>
            </div>
            <p>{brief.roleContext}</p>
          </section>
          <p className="prepared-time">
            <Clock3 size={12} />
            Sample prepared{" "}
            {new Date(brief.preparedAt).toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
            })}
          </p>
        </>
      )}
    </div>
  );
}

function QuestionList({ brief }: { brief: Brief }) {
  return (
    <ol className="question-list">
      {brief.questions.map((q, index) => (
        <li key={q.text}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <div>
            <p>{q.text}</p>
            <small>{q.basis}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Sources({ brief }: { brief: Brief | null }) {
  if (!brief?.sources.length)
    return (
      <EmptyState icon={<FileText size={24} />} title="No research sources yet">
        This demo has not researched this company. Your entered details are not
        treated as verified evidence.
      </EmptyState>
    );
  return (
    <div className="sources-panel">
      <div className="callout callout-neutral">
        <ShieldCheck size={17} />
        <p>
          These are fictional sample documents, not live research. Source URLs
          will appear here when the backend is connected.
        </p>
      </div>
      {brief.sources.map((source, index) => (
        <article className="source-document" key={source.id}>
          <div className="source-document-heading">
            <span className="source-index">{index + 1}</span>
            <div>
              <h3>{source.title}</h3>
              <p>{source.publisher}</p>
            </div>
            <span className="tiny-label">Sample</span>
          </div>
          <p className="source-excerpt">{source.excerpt}</p>
          {source.url && /^https?:\/\//.test(source.url) && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-link"
            >
              Open source <ArrowUpRight size={13} />
            </a>
          )}
        </article>
      ))}
    </div>
  );
}

export function BriefingPanel({
  prospect,
  position,
  total,
  onPrevious,
  onNext,
  onEdit,
  onResearch,
  onConnect,
  announce,
}: {
  prospect?: Prospect;
  position: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
  onEdit: () => void;
  onResearch: () => void;
  onConnect: () => void;
  announce: (text: string) => void;
}) {
  const [tab, setTab] = useState("overview");
  const uid = useId();
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [prospect?.id, tab]);
  useEffect(() => {
    setTab("overview");
  }, [prospect?.id]);
  const tabs = ["overview", "sources", "notes"];
  if (!prospect)
    return (
      <aside className="briefing-panel no-prospect">
        <EmptyState
          icon={<BookOpen size={26} />}
          title="Make room for a good conversation"
        >
          Select or add a prospect to bring their context into focus.
        </EmptyState>
      </aside>
    );
  return (
    <aside className="briefing-panel" aria-label="Prospect briefing">
      <div className="briefing-toolbar">
        <span className="eyebrow">PROSPECT BRIEFING</span>
        <div className="prospect-navigation">
          <span>
            {String(position + 1).padStart(2, "0")}{" "}
            <span className="muted">/ {String(total).padStart(2, "0")}</span>
          </span>
          <IconButton
            label="Previous prospect"
            disabled={position <= 0}
            onClick={onPrevious}
          >
            <ChevronLeft size={16} />
          </IconButton>
          <IconButton
            label="Next prospect"
            disabled={position >= total - 1}
            onClick={onNext}
          >
            <ChevronRight size={16} />
          </IconButton>
        </div>
      </div>
      <div className="prospect-heading">
        <div className="prospect-identity">
          <Avatar name={prospect.name} large index={position} />
          <div>
            <span className="company-kicker">{prospect.company}</span>
            <h2 id="prospect-title" tabIndex={-1}>
              {prospect.name}
            </h2>
            <p>{prospect.role}</p>
          </div>
          <Button
            onClick={onConnect}
            title="Mark connected when your external call connects"
          >
            <Phone size={15} />
            Call connected
          </Button>
        </div>
        <div className="contact-row">
          <span>
            <Phone size={13} />
            {prospect.phone || "No phone added"}
          </span>
          {prospect.phone && (
            <IconButton
              label="Copy phone number"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(prospect.phone);
                  announce("Phone number copied.");
                } catch {
                  announce(
                    "Could not copy. Select the phone number to copy it manually.",
                  );
                }
              }}
            >
              <Copy size={13} />
            </IconButton>
          )}
          <ResearchBadge status={prospect.researchStatus} />
          <IconButton label={`Edit ${prospect.name}`} onClick={onEdit}>
            <Pencil size={15} />
          </IconButton>
        </div>
      </div>
      <div className="brief-tabs" role="tablist" aria-label="Briefing sections">
        {tabs.map((value, index) => (
          <button
            key={value}
            role="tab"
            id={`${uid}-${value}`}
            aria-controls={`${uid}-panel`}
            aria-selected={tab === value}
            tabIndex={tab === value ? 0 : -1}
            onClick={() => setTab(value)}
            onKeyDown={(e) => {
              let next = index;
              if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
              else if (e.key === "ArrowLeft")
                next = (index + tabs.length - 1) % tabs.length;
              else if (e.key === "Home") next = 0;
              else if (e.key === "End") next = tabs.length - 1;
              else return;
              e.preventDefault();
              setTab(tabs[next]);
              document.getElementById(`${uid}-${tabs[next]}`)?.focus();
            }}
          >
            {value === "overview" ? (
              "Overview"
            ) : value === "sources" ? (
              <>
                Sources <span>{prospect.brief?.sources.length ?? 0}</span>
              </>
            ) : (
              "Your notes"
            )}
          </button>
        ))}
      </div>
      <div
        className="brief-tab-content"
        ref={contentRef}
        role="tabpanel"
        id={`${uid}-panel`}
        aria-labelledby={`${uid}-${tab}`}
        tabIndex={0}
      >
        {tab === "overview" ? (
          <BriefOverview
            prospect={prospect}
            onSources={() => setTab("sources")}
            onEdit={onEdit}
            onResearch={onResearch}
            onRetry={onResearch}
          />
        ) : tab === "sources" ? (
          <Sources brief={prospect.brief} />
        ) : (
          <section className="notes-tab">
            <span className="eyebrow">
              SELLER-PROVIDED · PRESERVED VERBATIM
            </span>
            <h3>What you already know</h3>
            <p className="seller-notes">
              {prospect.notes || "No notes entered for this prospect."}
            </p>
            <Button variant="secondary" small onClick={onEdit}>
              <Pencil size={14} />
              Edit notes
            </Button>
          </section>
        )}
      </div>
    </aside>
  );
}

export function OnCall({
  prospect,
  startedAt,
  onEnd,
}: {
  prospect: Prospect;
  startedAt: string;
  onEnd: (outcome: Outcome) => void;
}) {
  const [outcome, setOutcome] = useState<Outcome>("completed");
  const [elapsed, setElapsed] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
    const update = () =>
      setElapsed(
        Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000)),
      );
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [startedAt]);
  return (
    <main className="on-call-page" id="main-content">
      <div className="on-call-top">
        <span className="on-call-label">
          <span />
          IN CONVERSATION
        </span>
        <span
          className="call-timer"
          aria-label="Time since manually connecting"
        >
          <Clock3 size={14} />
          {Math.floor(elapsed / 60)
            .toString()
            .padStart(2, "0")}
          :{(elapsed % 60).toString().padStart(2, "0")}
        </span>
      </div>
      <header className="on-call-heading">
        <span className="company-kicker">{prospect.company}</span>
        <h1 ref={heading} tabIndex={-1}>
          {prospect.name}
        </h1>
        <p>
          {prospect.role}
          <span>·</span>
          {prospect.phone || "No phone added"}
        </p>
        <div className="manual-call-note">
          Manual call state. This app does not dial, listen, record, or
          transcribe.
        </div>
      </header>
      <div
        className="on-call-grid"
        role="region"
        aria-label="Call briefing"
        tabIndex={0}
      >
        <section className="on-call-notes">
          <div className="section-label">
            <FileText size={17} />
            <h2>Your notes, front and center.</h2>
          </div>
          <span className="tiny-label">Seller-provided</span>
          <p className="seller-notes">
            {prospect.notes ||
              "No seller notes yet. Use the prospect details and ask open-ended questions."}
          </p>
        </section>
        <section className="on-call-questions">
          <div className="section-label">
            <Lightbulb size={17} />
            <h2>Keep the conversation going</h2>
          </div>
          {prospect.brief ? (
            <QuestionList brief={prospect.brief} />
          ) : (
            <p className="muted">
              No prepared suggestions. Ask about their team’s current priorities
              and listen for context.
            </p>
          )}
          <p className="on-call-disclaimer">
            Suggestions are hypotheses. Let the prospect tell their story.
          </p>
        </section>
        <section className="on-call-company">
          <div className="section-label">
            <Building2 size={17} />
            <h2>Company context</h2>
            <span className="tiny-label">Sample</span>
          </div>
          <p>
            {prospect.brief?.summary ||
              "No company research is available. Only seller-provided details are shown."}
          </p>
          {prospect.brief?.facts.map((f) => (
            <p className="on-call-fact" key={f.label}>
              <strong>{f.label}</strong>
              {f.text}
            </p>
          ))}
          {!!prospect.brief?.uncertainty.length && (
            <div className="callout">
              <CircleAlert size={16} />
              <p>{prospect.brief.uncertainty.join(" ")}</p>
            </div>
          )}
        </section>
      </div>
      <footer className="on-call-footer">
        <div>
          <span className="eyebrow">WHEN YOU’RE FINISHED</span>
          <p>Save the outcome and return to your calling list.</p>
        </div>
        <label className="outcome-field">
          <span className="sr-only">Call outcome</span>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as Outcome)}
          >
            <option value="completed">Conversation completed</option>
            <option value="follow-up">Follow-up needed</option>
            <option value="not-interested">Not interested</option>
            <option value="no-answer">No answer</option>
          </select>
        </label>
        <Button variant="danger" onClick={() => onEnd(outcome)}>
          <Phone size={15} />
          End call
        </Button>
      </footer>
    </main>
  );
}

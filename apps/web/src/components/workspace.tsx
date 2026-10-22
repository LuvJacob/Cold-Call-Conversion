"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  Folder,
  Headphones,
  LayoutList,
  ListPlus,
  Menu,
  MoreHorizontal,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  makeProspect,
  prospectKey,
  type Outcome,
  type Prospect,
  type ProspectInput,
} from "@/lib/model";
import { useWorkspace } from "@/lib/use-workspace";
import {
  Avatar,
  Button,
  EmptyState,
  IconButton,
  Modal,
  ResearchBadge,
} from "./ui";
import {
  ConfirmDialog,
  ImportDialog,
  ListDialog,
  ProspectDialog,
} from "./prospect-dialogs";
import { BriefingPanel, OnCall } from "./briefing";

type DialogState =
  | { type: "prospect"; prospect: Prospect | null }
  | { type: "import" }
  | { type: "list"; rename?: boolean }
  | { type: "delete-prospect"; prospect: Prospect }
  | { type: "delete-list" }
  | { type: "reset" }
  | { type: "help" }
  | null;
const outcomes: Record<Outcome, string> = {
  completed: "Called",
  "follow-up": "Follow-up",
  "not-interested": "Not interested",
  "no-answer": "No answer",
};

export default function Workspace() {
  const {
    state,
    dispatch,
    loaded,
    storageWarning,
    storageConflict,
    savingAllowed,
    reset,
    retrySave,
  } = useWorkspace();
  const [listId, setListId] = useState("list-outreach");
  const [selectedId, setSelectedId] = useState("p-maya");
  const [view, setView] = useState<"workspace" | "library">("workspace");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [checked, setChecked] = useState<string[]>([]);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [notice, setNotice] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [showBrief, setShowBrief] = useState(false);
  const [menu, setMenu] = useState(false);
  const currentList =
    state.lists.find((l) => l.id === listId) ?? state.lists[0];
  const inList = state.prospects.filter((p) => p.listId === currentList.id);
  const base =
    view === "library" ? state.prospects.filter((p) => p.brief) : inList;
  const visible = useMemo(
    () =>
      base.filter((p) => {
        const searchMatch = `${p.name} ${p.company} ${p.role}`
          .toLowerCase()
          .includes(query.toLowerCase().trim());
        return (
          searchMatch &&
          (filter === "all" ||
            (filter === "prepared" && !!p.brief) ||
            (filter === "not-started" && p.researchStatus === "not-started") ||
            (filter === "attention" &&
              ["partial", "failed"].includes(p.researchStatus)) ||
            (filter === "called" && p.callStatus === "called"))
        );
      }),
    [base, query, filter],
  );
  const selected = visible.find((p) => p.id === selectedId) ?? visible[0];
  const position = visible.findIndex((p) => p.id === selected?.id);
  const active = state.prospects.find(
    (p) => p.id === state.activeCall?.prospectId,
  );
  const activeSelection = checked.filter((id) =>
    visible.some((p) => p.id === id),
  );
  const researchTargets = (
    activeSelection.length
      ? visible.filter((p) => activeSelection.includes(p.id))
      : visible.filter((p) => !p.brief)
  ).filter((p) => p.researchStatus !== "running");
  const running = state.prospects.filter(
    (p) => p.researchStatus === "running",
  ).length;
  const prepared = base.filter((p) => !!p.brief).length;
  const called = base.filter((p) => p.callStatus === "called").length;
  const attention = base.filter(
    (p) => p.researchStatus === "partial" || p.researchStatus === "failed",
  ).length;

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 6000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    setChecked([]);
  }, [listId, query, filter, view]);
  useEffect(() => {
    if (!menu) return;
    const dismiss = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("keydown", dismiss);
    return () => document.removeEventListener("keydown", dismiss);
  }, [menu]);

  function chooseList(id: string) {
    setListId(id);
    setView("workspace");
    setQuery("");
    setFilter("all");
    setSelectedId(state.prospects.find((p) => p.listId === id)?.id ?? "");
    setMobileNav(false);
    setShowBrief(false);
    setMenu(false);
  }
  function research(ids: string[]) {
    dispatch({ type: "research-start", ids });
    setNotice(
      `Preparing ${ids.length === 1 ? "a sample briefing" : `${ids.length} sample briefings`}. No live research is performed.`,
    );
  }
  function saveProspect(input: ProspectInput) {
    const editing = dialog?.type === "prospect" ? dialog.prospect : null;
    const targetList = editing?.listId ?? currentList.id;
    if (
      state.prospects.some(
        (p) =>
          p.id !== editing?.id &&
          prospectKey(p) === prospectKey({ ...input, listId: targetList }),
      )
    )
      return "This person, company, and role already exist in this list.";
    if (!editing && state.prospects.length >= 1000)
      return "This demo workspace supports up to 1,000 prospects. Remove some before adding more.";
    if (editing) {
      dispatch({ type: "save-prospect", prospect: { ...editing, ...input } });
      setSelectedId(editing.id);
      setNotice(
        "Prospect updated. Prepare a new sample brief when you’re ready.",
      );
    } else {
      const p = makeProspect(input, targetList);
      dispatch({ type: "add-prospects", prospects: [p] });
      setSelectedId(p.id);
      setNotice(`${p.name} added to ${currentList.name}.`);
    }
    setView("workspace");
    setListId(targetList);
    setQuery("");
    setFilter("all");
    setShowBrief(true);
    setDialog(null);
  }
  function endCall(outcome: Outcome) {
    if (!active) return;
    const list = state.prospects.filter((p) => p.listId === active.listId);
    const next =
      list
        .slice(list.findIndex((p) => p.id === active.id) + 1)
        .find((p) => p.callStatus === "ready") ??
      list.find((p) => p.id !== active.id && p.callStatus === "ready");
    dispatch({ type: "end-call", outcome, now: new Date().toISOString() });
    setListId(active.listId);
    setView("workspace");
    setQuery("");
    setFilter("all");
    setSelectedId(next?.id ?? active.id);
    setShowBrief(false);
    setNotice(
      `Call with ${active.name} saved: ${outcomes[outcome].toLowerCase()}.${next ? ` Next up: ${next.name}.` : ""}`,
    );
    requestAnimationFrame(() =>
      document.getElementById("workspace-title")?.focus(),
    );
  }
  const nav = (
    <>
      <a
        href="#main-content"
        className="brand"
        aria-label="Cold Call Conversion home"
        onClick={() => {
          setView("workspace");
          setMobileNav(false);
        }}
      >
        <span className="brand-symbol">
          <Phone size={22} strokeWidth={1.8} />
        </span>
        <span>
          cold call<span>conversion</span>
        </span>
        <span className="brand-dot" />
      </a>
      <div className="workspace-switch">
        <span className="workspace-avatar">D</span>
        <div>
          <strong>Demo workspace</strong>
          <small>Local to this browser</small>
        </div>
        <span className="tiny-label">DEMO</span>
      </div>
      <nav aria-label="Main navigation" className="main-nav">
        <button
          className={view === "workspace" ? "nav-item selected" : "nav-item"}
          onClick={() => {
            setView("workspace");
            setQuery("");
            setFilter("all");
            setMobileNav(false);
          }}
        >
          <LayoutList size={18} />
          Calling workspace
          {view === "workspace" && <span className="nav-indicator" />}
        </button>
        <button
          className={view === "library" ? "nav-item selected" : "nav-item"}
          onClick={() => {
            setView("library");
            setQuery("");
            setFilter("all");
            setMobileNav(false);
          }}
        >
          <BookOpen size={18} />
          Briefing library
          <span className="nav-count">
            {state.prospects.filter((p) => p.brief).length}
          </span>
        </button>
      </nav>
      <div className="sidebar-label">
        <span>YOUR CALLING LISTS</span>
        <IconButton
          label="Create calling list"
          disabled={state.lists.length >= 50}
          onClick={() => {
            setMobileNav(false);
            setDialog({ type: "list" });
          }}
        >
          <Plus size={15} />
        </IconButton>
      </div>
      <nav aria-label="Calling lists" className="list-nav">
        {state.lists.map((l) => (
          <button
            key={l.id}
            className={
              view === "workspace" && currentList.id === l.id
                ? "list-nav-item active"
                : "list-nav-item"
            }
            onClick={() => chooseList(l.id)}
          >
            <span className="list-dot" />
            <span>{l.name}</span>
            <small>
              {state.prospects.filter((p) => p.listId === l.id).length}
            </small>
          </button>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <span className="sidebar-note-icon">
            <Headphones size={22} strokeWidth={1.5} />
          </span>
          <strong>
            A little preparation.
            <br />A better conversation.
          </strong>
          <p>
            Keep the context close.
            <br />
            Focus on the person.
          </p>
        </div>
        <button
          className="nav-item"
          onClick={() => {
            setMobileNav(false);
            setDialog({ type: "help" });
          }}
        >
          <CircleHelp size={17} />
          Workspace guide
          <ArrowRight size={14} />
        </button>
        <div className="sidebar-user">
          <span className="user-avatar">D</span>
          <div>
            <strong>Demo seller</strong>
            <small>No sign-in required</small>
          </div>
        </div>
      </div>
    </>
  );
  if (!loaded)
    return (
      <div className="loading-workspace">
        <span className="brand-symbol">
          <Phone size={24} />
        </span>
        <p>Opening your workspace…</p>
      </div>
    );

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to calling workspace
      </a>
      <div className="app-shell">
        <aside className="sidebar">{nav}</aside>
        <div className="app-main">
          <header className="topbar">
            <div className="breadcrumbs">
              <span className="mobile-menu">
                <IconButton
                  label="Open navigation"
                  onClick={() => setMobileNav(true)}
                >
                  <Menu size={20} />
                </IconButton>
              </span>
              <span>Workspace</span>
              <ChevronRight size={13} />
              <strong>
                {active
                  ? "On call"
                  : view === "library"
                    ? "Briefing library"
                    : currentList.name}
              </strong>
            </div>
            <div className="save-status">
              <span
                className={storageWarning ? "status-dot warning" : "status-dot"}
              />
              {storageWarning ? "Session only" : "Saved in this browser"}
              <span className="topbar-divider" />
              <span className="demo-pill">DEMO</span>
            </div>
          </header>
          {storageWarning && (
            <div className="storage-warning" role="alert">
              <p>{storageWarning}</p>
              <Button
                small
                variant="secondary"
                disabled={!savingAllowed && !storageConflict}
                onClick={
                  storageConflict ? () => window.location.reload() : retrySave
                }
              >
                {storageConflict ? "Reload latest workspace" : "Retry saving"}
              </Button>
            </div>
          )}
          <div className="demo-banner">
            <span className="demo-banner-icon">
              <FileText size={13} />
            </span>
            <p>
              <strong>A working preview.</strong> Fictional sample data and
              simulated research. Your changes stay in this browser.
            </p>
            <button onClick={() => setDialog({ type: "help" })}>
              How it works <ArrowUpRightIcon />
            </button>
          </div>
          {active && state.activeCall ? (
            <OnCall
              prospect={active}
              startedAt={state.activeCall.startedAt}
              onEnd={endCall}
            />
          ) : (
            <main className="workspace-page" id="main-content">
              <header className="page-heading">
                <div>
                  <span className="eyebrow">
                    {view === "library"
                      ? "YOUR PREPARED CONTEXT"
                      : "MAKE THE FIRST CONVERSATION COUNT"}
                  </span>
                  <h1 id="workspace-title" tabIndex={-1}>
                    {view === "library"
                      ? "Briefing library"
                      : "Calling workspace"}
                    <span className="heading-period">.</span>
                  </h1>
                  <p>
                    {view === "library"
                      ? "Prepared context, ready to revisit across your calling lists."
                      : "Know a little more before you say hello."}
                  </p>
                </div>
                <div className="heading-actions">
                  <Button
                    variant="secondary"
                    onClick={() => setDialog({ type: "import" })}
                  >
                    <Upload size={15} />
                    Import CSV
                  </Button>
                  <Button
                    onClick={() =>
                      setDialog({ type: "prospect", prospect: null })
                    }
                  >
                    <Plus size={16} />
                    Add prospect
                  </Button>
                </div>
              </header>
              <div
                className="workspace-stats"
                aria-label="Calling list statistics"
              >
                <div>
                  <span className="stat-value">
                    {String(base.length).padStart(2, "0")}
                  </span>
                  <span>Prospects</span>
                </div>
                <div>
                  <span className="stat-value green">
                    {String(prepared).padStart(2, "0")}
                  </span>
                  <span>Briefs prepared</span>
                </div>
                <div>
                  <span className="stat-value">
                    {String(attention).padStart(2, "0")}
                  </span>
                  <span>Need a closer look</span>
                </div>
                <div>
                  <span className="stat-value">
                    {String(called).padStart(2, "0")}
                  </span>
                  <span>Calls completed</span>
                </div>
                <div className="session-progress">
                  <span>
                    {called === base.length && base.length
                      ? "A good day’s work."
                      : "One conversation at a time."}
                  </span>
                  <div className="progress-track">
                    <span
                      style={{
                        width: `${base.length ? (called / base.length) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <small>
                    {called} of {base.length} prospects called
                  </small>
                </div>
              </div>
              <div
                className={`workspace-grid ${showBrief ? "mobile-show-brief" : ""}`}
              >
                <section
                  className="queue-panel"
                  aria-label="Prospect calling queue"
                >
                  <div className="queue-heading">
                    <div>
                      <span className="eyebrow">
                        {view === "library"
                          ? "ALL CALLING LISTS"
                          : "YOUR CALLING LIST"}
                      </span>
                      <h2>
                        {view === "library"
                          ? "Prepared briefings"
                          : currentList.name}
                        <span>{base.length}</span>
                      </h2>
                    </div>
                    {view === "workspace" && (
                      <div className="list-menu-container">
                        <IconButton
                          label="Calling list options"
                          aria-expanded={menu}
                          onClick={() => setMenu((v) => !v)}
                        >
                          <MoreHorizontal size={20} />
                        </IconButton>
                        {menu && (
                          <>
                            <button
                              className="menu-dismiss"
                              aria-label="Close list options"
                              tabIndex={-1}
                              onClick={() => setMenu(false)}
                            />
                            <div className="list-menu">
                              <button
                                onClick={() => {
                                  setMenu(false);
                                  setDialog({ type: "list", rename: true });
                                }}
                              >
                                <Pencil size={14} />
                                Rename list
                              </button>
                              <button
                                disabled={state.lists.length === 1}
                                onClick={() => {
                                  setMenu(false);
                                  setDialog({ type: "delete-list" });
                                }}
                              >
                                <Trash2 size={14} />
                                Delete list
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="queue-filters">
                    <label className="search-field">
                      <Search size={16} />
                      <input
                        placeholder="Find a person or company"
                        aria-label="Search prospects"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                      {query && (
                        <button
                          aria-label="Clear search"
                          onClick={() => setQuery("")}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </label>
                    <label className="filter-field">
                      <span className="sr-only">Filter prospects</span>
                      <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option value="all">All prospects</option>
                        <option value="prepared">Brief prepared</option>
                        <option value="not-started">Not prepared</option>
                        <option value="attention">Needs attention</option>
                        <option value="called">Called</option>
                      </select>
                    </label>
                  </div>
                  <div className="queue-column-head">
                    <label className="select-all">
                      <input
                        type="checkbox"
                        aria-label="Select all visible prospects"
                        checked={
                          visible.length > 0 &&
                          activeSelection.length === visible.length
                        }
                        onChange={(e) =>
                          setChecked(
                            e.target.checked ? visible.map((p) => p.id) : [],
                          )
                        }
                        disabled={!visible.length}
                      />
                      <span>
                        {activeSelection.length
                          ? `${activeSelection.length} SELECTED`
                          : "PROSPECT"}
                      </span>
                    </label>
                    <span>PREPARATION</span>
                  </div>
                  <div
                    className="prospect-rows"
                    role="region"
                    aria-label="Contacts"
                    tabIndex={0}
                  >
                    {visible.map((p, index) => (
                      <div
                        key={p.id}
                        className={`prospect-row ${selected?.id === p.id ? "is-selected" : ""}`}
                      >
                        <input
                          type="checkbox"
                          aria-label={`Select ${p.name} for research`}
                          checked={activeSelection.includes(p.id)}
                          onChange={(e) =>
                            setChecked((ids) =>
                              e.target.checked
                                ? [...ids, p.id]
                                : ids.filter((id) => id !== p.id),
                            )
                          }
                        />
                        <button
                          id={`prospect-${p.id}`}
                          className="prospect-select"
                          onClick={() => {
                            setSelectedId(p.id);
                            setShowBrief(true);
                            if (window.matchMedia("(max-width: 740px)").matches)
                              requestAnimationFrame(() =>
                                document
                                  .getElementById("prospect-title")
                                  ?.focus(),
                              );
                          }}
                          aria-pressed={selected?.id === p.id}
                          aria-label={`View ${p.name}`}
                        >
                          <Avatar name={p.name} index={index} />
                          <span className="row-person">
                            <strong>{p.name}</strong>
                            <span>{p.role}</span>
                            <small>{p.company}</small>
                          </span>
                          <span className="row-status">
                            <ResearchBadge status={p.researchStatus} />
                            {p.callStatus === "called" && (
                              <span className="call-outcome">
                                <Check size={10} />
                                {p.outcome ? outcomes[p.outcome] : "Called"}
                              </span>
                            )}
                          </span>
                          <ChevronRight size={14} className="row-chevron" />
                        </button>
                      </div>
                    ))}
                    {!visible.length && (
                      <EmptyState
                        icon={
                          base.length ? (
                            <Search size={25} />
                          ) : (
                            <ListPlus size={25} />
                          )
                        }
                        title={
                          base.length
                            ? "No matching prospects"
                            : view === "library"
                              ? "Your briefings will live here"
                              : "Your next conversation starts here"
                        }
                        action={
                          base.length ? (
                            <Button
                              small
                              variant="secondary"
                              onClick={() => {
                                setQuery("");
                                setFilter("all");
                              }}
                            >
                              Clear filters
                            </Button>
                          ) : (
                            <Button
                              small
                              variant="secondary"
                              onClick={() =>
                                setDialog({ type: "prospect", prospect: null })
                              }
                            >
                              <Plus size={14} />
                              Add a prospect
                            </Button>
                          )
                        }
                      >
                        {base.length
                          ? "Try another name, company, or preparation filter."
                          : view === "library"
                            ? "Prepare a sample briefing from your calling workspace to see it here."
                            : "Add a prospect or import a CSV to build this calling list."}
                      </EmptyState>
                    )}
                  </div>
                  <div className="queue-footer">
                    <span>
                      {visible.length} of {base.length} prospects
                    </span>
                    <Button
                      small
                      variant="secondary"
                      disabled={!researchTargets.length}
                      onClick={() => research(researchTargets.map((p) => p.id))}
                    >
                      <RefreshCw size={13} />
                      {activeSelection.length
                        ? `Prepare ${researchTargets.length} selected`
                        : "Prepare missing briefs"}
                    </Button>
                  </div>
                  {!!running && (
                    <p className="queue-working" role="status">
                      <span className="status-dot" />
                      Preparing {running} sample briefing
                      {running === 1 ? "" : "s"}…
                    </p>
                  )}
                  {selected && (
                    <div className="prospect-actions">
                      <span className="muted">Selected prospect</span>
                      <div>
                        <IconButton
                          label={`Move ${selected.name} up`}
                          disabled={
                            view === "library" ||
                            inList.findIndex((p) => p.id === selected.id) <= 0
                          }
                          onClick={() =>
                            dispatch({
                              type: "move",
                              id: selected.id,
                              direction: -1,
                            })
                          }
                        >
                          <ArrowUp size={14} />
                        </IconButton>
                        <IconButton
                          label={`Move ${selected.name} down`}
                          disabled={
                            view === "library" ||
                            inList.findIndex((p) => p.id === selected.id) >=
                              inList.length - 1
                          }
                          onClick={() =>
                            dispatch({
                              type: "move",
                              id: selected.id,
                              direction: 1,
                            })
                          }
                        >
                          <ArrowDown size={14} />
                        </IconButton>
                        <IconButton
                          label={`Edit selected prospect`}
                          onClick={() =>
                            setDialog({ type: "prospect", prospect: selected })
                          }
                        >
                          <Pencil size={14} />
                        </IconButton>
                        <IconButton
                          label={`Remove ${selected.name}`}
                          onClick={() =>
                            setDialog({
                              type: "delete-prospect",
                              prospect: selected,
                            })
                          }
                        >
                          <Trash2 size={14} />
                        </IconButton>
                      </div>
                    </div>
                  )}
                  <div className="queue-tip">
                    <span className="tip-rule" />
                    <p>
                      <strong>Context makes the difference.</strong>
                      <br />
                      Review your notes and research before connecting.
                    </p>
                  </div>
                </section>
                <div className="detail-column">
                  <button
                    className="mobile-back text-link"
                    onClick={() => {
                      setShowBrief(false);
                      requestAnimationFrame(() =>
                        document
                          .getElementById(`prospect-${selected?.id}`)
                          ?.focus(),
                      );
                    }}
                  >
                    ← Back to calling list
                  </button>
                  <BriefingPanel
                    prospect={selected}
                    position={position}
                    total={visible.length}
                    onPrevious={() =>
                      setSelectedId(visible[position - 1]?.id ?? "")
                    }
                    onNext={() =>
                      setSelectedId(visible[position + 1]?.id ?? "")
                    }
                    onEdit={() =>
                      selected &&
                      setDialog({ type: "prospect", prospect: selected })
                    }
                    onResearch={() => selected && research([selected.id])}
                    onConnect={() => {
                      if (selected) {
                        dispatch({
                          type: "connect",
                          id: selected.id,
                          now: new Date().toISOString(),
                        });
                        window.scrollTo({ top: 0 });
                      }
                    }}
                    announce={setNotice}
                  />
                  {selected?.callStatus === "called" && (
                    <button
                      className="reset-call text-link"
                      onClick={() => {
                        dispatch({ type: "reset-call", id: selected.id });
                        setNotice(
                          "Prospect returned to ready. Previous call history is retained.",
                        );
                      }}
                    >
                      Return prospect to ready <ArrowRight size={13} />
                    </button>
                  )}
                </div>
              </div>
              <footer className="workspace-footer">
                <span>Built for the conversation ahead.</span>
                <button onClick={() => setDialog({ type: "reset" })}>
                  Reset demo workspace
                </button>
              </footer>
            </main>
          )}
        </div>
      </div>
      {notice && (
        <div className="toast" role="status">
          <Check size={16} />
          <span>{notice}</span>
          <IconButton
            label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </IconButton>
        </div>
      )}
      {mobileNav && (
        <Modal
          open
          onClose={() => setMobileNav(false)}
          title="Your workspace"
          description="Choose a calling list or open your prepared briefings."
        >
          <div className="mobile-navigation">{nav}</div>
        </Modal>
      )}
      {dialog?.type === "prospect" && (
        <ProspectDialog
          prospect={dialog.prospect}
          onClose={() => setDialog(null)}
          onSave={saveProspect}
        />
      )}
      {dialog?.type === "import" && (
        <ImportDialog
          listId={currentList.id}
          existing={state.prospects}
          capacity={1000 - state.prospects.length}
          onClose={() => setDialog(null)}
          onImport={(prospects, duplicates) => {
            dispatch({ type: "add-prospects", prospects });
            chooseList(currentList.id);
            setSelectedId(prospects[0]?.id ?? "");
            setDialog(null);
            setNotice(
              `Imported ${prospects.length} prospects.${duplicates ? ` Skipped ${duplicates} duplicates.` : ""}`,
            );
          }}
        />
      )}
      {dialog?.type === "list" && (
        <ListDialog
          name={dialog.rename ? currentList.name : undefined}
          onClose={() => setDialog(null)}
          onSave={(name) => {
            if (dialog.rename) {
              dispatch({ type: "rename-list", id: currentList.id, name });
              setNotice("Calling list renamed.");
            } else {
              const id = crypto.randomUUID();
              dispatch({ type: "add-list", id, name });
              chooseList(id);
              setNotice("Calling list created. Add your first prospect.");
            }
            setDialog(null);
          }}
        />
      )}
      {dialog?.type === "delete-prospect" && (
        <ConfirmDialog
          title={`Remove ${dialog.prospect.name}?`}
          description="This removes their prospect details, saved briefing, and call history from this browser. This cannot be undone."
          label="Remove prospect"
          onClose={() => setDialog(null)}
          onConfirm={() => {
            dispatch({ type: "delete-prospect", id: dialog.prospect.id });
            setDialog(null);
            setNotice("Prospect removed.");
          }}
        />
      )}
      {dialog?.type === "delete-list" && (
        <ConfirmDialog
          title={`Delete ${currentList.name}?`}
          description={`This permanently removes this list and its ${inList.length} prospects, briefings, and call history from this browser.`}
          label="Delete list"
          onClose={() => setDialog(null)}
          onConfirm={() => {
            dispatch({ type: "delete-list", id: currentList.id });
            chooseList(state.lists.find((l) => l.id !== currentList.id)!.id);
            setDialog(null);
            setNotice("Calling list deleted.");
          }}
        />
      )}
      {dialog?.type === "reset" && (
        <ConfirmDialog
          title="Start fresh with sample data?"
          description="This replaces every list, prospect, briefing, and call outcome saved by this demo in this browser. Your changes cannot be recovered."
          label="Reset demo"
          onClose={() => setDialog(null)}
          onConfirm={() => {
            reset();
            chooseList("list-outreach");
            setSelectedId("p-maya");
            setDialog(null);
            setNotice("Original sample workspace restored.");
          }}
        />
      )}
      {dialog?.type === "help" && (
        <Modal
          open
          onClose={() => setDialog(null)}
          title="A workspace for better conversations"
          description="Explore the complete calling flow with clearly labeled sample information."
        >
          <ol className="guide-steps">
            <li>
              <span>01</span>
              <div>
                <h3>Build your calling list</h3>
                <p>
                  Add prospects individually or import a CSV. Keep the details
                  and notes you already have.
                </p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <h3>Prepare the context</h3>
                <p>
                  Prepare sample briefs and review the source panel. New
                  prospects receive general guidance, never invented company
                  facts.
                </p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <h3>Focus on the conversation</h3>
                <p>
                  Make your call externally. Select Call connected to open the
                  focused view, then End call to save the outcome.
                </p>
              </div>
            </li>
          </ol>
          <div className="callout callout-neutral">
            <p>
              This frontend demo has no backend, live AI, authentication, or
              actual dialing. Data stays in this browser. Clearing browser
              storage removes it.
            </p>
          </div>
          <div className="dialog-footer">
            <Button onClick={() => setDialog(null)}>
              Got it <ArrowRight size={14} />
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

function ArrowUpRightIcon() {
  return <ChevronRight size={13} />;
}

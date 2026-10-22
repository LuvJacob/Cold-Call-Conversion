"use client";

import { useRef, useState, type FormEvent } from "react";
import {
  Check,
  Download,
  FileSpreadsheet,
  Upload,
  AlertCircle,
} from "lucide-react";
import {
  makeProspect,
  prospectInputSchema,
  prospectKey,
  type Prospect,
  type ProspectInput,
} from "@/lib/model";
import { parseProspectCsv, type CsvResult } from "@/lib/csv";
import { Button, Modal } from "./ui";

export function ProspectDialog({
  prospect,
  onClose,
  onSave,
}: {
  prospect: Prospect | null;
  onClose: () => void;
  onSave: (input: ProspectInput) => string | void;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const result = prospectInputSchema.safeParse(data);
    if (!result.success) {
      setErrors(
        Object.fromEntries(
          result.error.issues.map((i) => [String(i.path[0]), i.message]),
        ),
      );
      return;
    }
    const message = onSave(result.data);
    if (message) setError(message);
  }
  return (
    <Modal
      open
      onClose={onClose}
      title={prospect ? "Edit prospect" : "A new conversation starts here"}
      description={
        prospect
          ? "Changes clear the old sample briefing so it cannot be mistaken for current research."
          : "Add what you know. Your notes stay separate from research."
      }
    >
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          {(
            [
              ["name", "Full name", "e.g. Alex Chen"],
              ["company", "Company", "e.g. Acme"],
              ["role", "Job title", "e.g. Director of IT"],
              ["phone", "Phone · optional", "+1 (555) 000-0000"],
            ] as const
          ).map(([name, label, placeholder]) => (
            <label className="field" key={name}>
              <span>{label}</span>
              <input
                name={name}
                defaultValue={prospect?.[name] ?? ""}
                placeholder={placeholder}
                autoComplete="off"
                type={name === "phone" ? "tel" : "text"}
                maxLength={name === "phone" ? 80 : name === "name" ? 120 : 160}
                aria-invalid={!!errors[name]}
                aria-describedby={errors[name] ? `error-${name}` : undefined}
              />
              {errors[name] && (
                <small id={`error-${name}`} className="field-error">
                  {errors[name]}
                </small>
              )}
            </label>
          ))}
        </div>
        <label className="field">
          <span>
            Your notes <span className="muted">· optional</span>
          </span>
          <textarea
            name="notes"
            rows={5}
            defaultValue={prospect?.notes ?? ""}
            maxLength={4000}
            placeholder="Previous conversations, technical environment, or something worth asking about…"
            aria-invalid={!!errors.notes}
          />
          <small>
            Saved exactly as entered. These are your notes, not verified
            research.
          </small>
          {errors.notes && (
            <small className="field-error">{errors.notes}</small>
          )}
        </label>
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">
            {prospect ? "Save changes" : "Add prospect"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function ListDialog({
  name,
  onClose,
  onSave,
}: {
  name?: string;
  onClose: () => void;
  onSave: (name: string) => void;
}) {
  const [error, setError] = useState("");
  return (
    <Modal
      open
      onClose={onClose}
      title={name ? "Rename calling list" : "Create a calling list"}
      description="Keep a group of prospects together for your next calling session."
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const value = String(
            new FormData(e.currentTarget).get("name") ?? "",
          ).trim();
          if (!value) {
            setError("Give this list a name.");
            return;
          }
          onSave(value);
        }}
        noValidate
      >
        <label className="field">
          <span>List name</span>
          <input
            name="name"
            placeholder="e.g. November outreach"
            maxLength={80}
            defaultValue={name ?? ""}
            aria-invalid={!!error}
          />
          {error && <small className="field-error">{error}</small>}
        </label>
        <div className="dialog-footer">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">{name ? "Save name" : "Create list"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function ConfirmDialog({
  title,
  description,
  label,
  onClose,
  onConfirm,
}: {
  title: string;
  description: string;
  label: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal open onClose={onClose} title={title} description={description}>
      <div className="dialog-footer">
        <Button variant="secondary" autoFocus onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" onClick={onConfirm}>
          {label}
        </Button>
      </div>
    </Modal>
  );
}

export function ImportDialog({
  listId,
  existing,
  capacity,
  onClose,
  onImport,
}: {
  listId: string;
  existing: Prospect[];
  capacity: number;
  onClose: () => void;
  onImport: (prospects: Prospect[], duplicates: number) => void;
}) {
  const [result, setResult] = useState<CsvResult | null>(null);
  const [filename, setFilename] = useState("");
  const [fileError, setFileError] = useState("");
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const keys = new Set(existing.map(prospectKey));
  let duplicates = 0;
  const additions = (result?.rows ?? []).filter((p) => {
    const key = prospectKey({ ...p, listId });
    if (keys.has(key)) {
      duplicates++;
      return false;
    }
    keys.add(key);
    return true;
  });
  async function readFile(file?: File) {
    if (!file) return;
    const ticket = ++request.current;
    setFileError("");
    setResult(null);
    setFilename(file.name);
    if (file.size > 1_000_000) {
      setFileError("Choose a CSV smaller than 1 MB.");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const text = await file.text();
      if (ticket === request.current) setResult(parseProspectCsv(text));
    } catch {
      if (ticket === request.current)
        setFileError("This file could not be read. Try choosing it again.");
    } finally {
      if (ticket === request.current) setLoading(false);
    }
  }
  const template =
    "name,company,role,phone,notes\nAlex Chen,Example Company,Director of IT,,Introductory conversation\n";
  return (
    <Modal
      open
      onClose={onClose}
      title="Bring your calling list"
      description="Import a CSV, review the preview, and add the valid prospects. Nothing is uploaded to a server."
      wide
    >
      <div
        className="upload-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void readFile(e.dataTransfer.files[0]);
        }}
      >
        <FileSpreadsheet size={30} strokeWidth={1.5} />
        <strong>{filename || "Drop a CSV file here"}</strong>
        <span>
          {loading
            ? "Reading your file…"
            : "Up to 500 prospects · 1 MB maximum"}
        </span>
        <Button
          variant="secondary"
          small
          onClick={() => input.current?.click()}
        >
          <Upload size={14} />
          {filename ? "Choose another file" : "Choose CSV"}
        </Button>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          aria-label="CSV file"
          className="sr-only"
          onChange={(e) => {
            void readFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      <div className="import-help">
        <p>
          Required: <code>name</code>, <code>company</code>, <code>role</code>
          <br />
          Optional: <code>phone</code>, <code>notes</code>. <code>title</code>{" "}
          also works for role.
        </p>
        <a
          className="text-link"
          href={`data:text/csv;charset=utf-8,${encodeURIComponent(template)}`}
          download="prospect-template.csv"
        >
          <Download size={14} />
          CSV template
        </a>
      </div>
      {fileError && (
        <p role="alert" className="inline-error">
          {fileError}
        </p>
      )}
      {result && (
        <div className="import-preview">
          <div className="preview-counts">
            <span>
              <Check size={14} />
              {additions.length} new prospects
            </span>
            {duplicates > 0 && (
              <span>
                {duplicates} duplicate{duplicates !== 1 ? "s" : ""} skipped
              </span>
            )}
            {result.errors.length > 0 && (
              <span className="warning-text">
                {result.errors.length} issue
                {result.errors.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          {!!additions.length && (
            <div className="preview-table-wrap">
              <table className="preview-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Role</th>
                  </tr>
                </thead>
                <tbody>
                  {additions.slice(0, 5).map((p, i) => (
                    <tr key={i}>
                      <td>{p.name}</td>
                      <td>{p.company}</td>
                      <td>{p.role}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {additions.length > 5 && (
                <p className="muted">
                  Previewing 5 of {additions.length} new prospects.
                </p>
              )}
            </div>
          )}
          {!!result.errors.length && (
            <div className="import-errors" role="alert">
              <strong>
                <AlertCircle size={14} />
                Rows with errors will not be imported.
              </strong>
              <ul>
                {result.errors.slice(0, 10).map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
              {result.errors.length > 10 && (
                <p>And {result.errors.length - 10} more issues.</p>
              )}
            </div>
          )}
          {additions.length > capacity && (
            <p role="alert" className="inline-error">
              This workspace has room for {capacity} more prospects. Reduce the
              file before importing.
            </p>
          )}
        </div>
      )}
      <div className="dialog-footer">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={loading || !additions.length || additions.length > capacity}
          onClick={() =>
            onImport(
              additions.map((p) => makeProspect(p, listId)),
              duplicates,
            )
          }
        >
          Import {additions.length || ""} valid prospect
          {additions.length !== 1 ? "s" : ""}
        </Button>
      </div>
    </Modal>
  );
}

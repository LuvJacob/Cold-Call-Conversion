import type { Brief, Outcome, Prospect, WorkspaceState } from "./model.ts";

// All calls go through the Next.js proxy (app/api/[...path]/route.ts), which
// adds the seller header server-side. The browser never sees the API address.
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (json !== undefined) headers.set("content-type", "application/json");
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...rest,
      headers,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("The server could not be reached.", 0);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg)
        detail = String(body.detail[0].msg);
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

type ApiProspect = Omit<Prospect, "researchStatus" | "brief"> & {
  researchStatus: Prospect["researchStatus"] | "queued";
  brief: Brief | null;
};
export type ApiWorkspace = Omit<WorkspaceState, "prospects"> & {
  prospects: ApiProspect[];
};
export type ResearchStatusResponse = {
  prospectId: string;
  revision: number;
  researchStatus: ApiProspect["researchStatus"];
};

// Backend "queued" and "running" both mean research is in flight.
export function toProspect(p: ApiProspect): Prospect {
  const { researchStatus, ...rest } = p;
  return {
    ...rest,
    researchStatus: researchStatus === "queued" ? "running" : researchStatus,
  };
}
export function toWorkspace(w: ApiWorkspace): WorkspaceState {
  return { ...w, prospects: w.prospects.map(toProspect) };
}

type Fields = {
  name: string;
  company: string;
  role: string;
  phone: string;
  notes: string;
  companyDomain?: string | null;
};
const fields = (i: Fields): Fields => ({
  name: i.name,
  company: i.company,
  role: i.role,
  phone: i.phone,
  notes: i.notes,
  companyDomain: i.companyDomain || null,
});

export const api = {
  workspace: () => call<ApiWorkspace>("/workspace").then(toWorkspace),
  createList: (name: string) =>
    call<{ id: string }>("/lists", { method: "POST", json: { name } }),
  renameList: (id: string, name: string) =>
    call(`/lists/${encodeURIComponent(id)}`, {
      method: "PATCH",
      json: { name },
    }),
  deleteList: (id: string) =>
    call(`/lists/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createProspects: (listId: string, inputs: Fields[]) =>
    call<ApiProspect[]>(`/lists/${encodeURIComponent(listId)}/prospects`, {
      method: "POST",
      json: inputs.map(fields),
    }).then((r) => r.map(toProspect)),
  importCsv: (listId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<{ imported: ApiProspect[]; duplicatesSkipped: number }>(
      `/lists/${encodeURIComponent(listId)}/import`,
      { method: "POST", body: form },
    ).then((r) => ({
      imported: r.imported.map(toProspect),
      duplicatesSkipped: r.duplicatesSkipped,
    }));
  },
  updateProspect: (id: string, input: Fields) =>
    call(`/prospects/${encodeURIComponent(id)}`, {
      method: "PATCH",
      // "" clears the domain on the backend; omitted leaves it unchanged.
      json: { ...fields(input), companyDomain: input.companyDomain ?? "" },
    }),
  deleteProspect: (id: string) =>
    call(`/prospects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  moveProspect: (id: string, direction: -1 | 1) =>
    call(`/prospects/${encodeURIComponent(id)}/move`, {
      method: "POST",
      json: { direction },
    }),
  startResearch: (prospectIds: string[]) =>
    call("/research", { method: "POST", json: { prospectIds } }),
  researchStatus: (id: string) =>
    call<ResearchStatusResponse>(
      `/prospects/${encodeURIComponent(id)}/research`,
    ),
  connect: (prospectId: string) =>
    call("/calls", { method: "POST", json: { prospectId } }),
  endCall: (outcome: Outcome) =>
    call("/calls/end", {
      method: "POST",
      json: { outcome },
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  resetCall: (id: string) =>
    call(`/calls/reset/${encodeURIComponent(id)}`, { method: "POST" }),
};

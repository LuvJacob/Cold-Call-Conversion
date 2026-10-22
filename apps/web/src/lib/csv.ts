import { prospectInputSchema, type ProspectInput } from "./model.ts";

export type CsvResult = {
  rows: ProspectInput[];
  errors: string[];
  total: number;
};
export function parseProspectCsv(text: string): CsvResult {
  const fail = (message: string): CsvResult => ({
    rows: [],
    errors: [message],
    total: 0,
  });
  if (text.length > 1_000_000) return fail("Choose a CSV smaller than 1 MB.");
  const records: string[][] = [];
  let row: string[] = [],
    value = "",
    quoted = false,
    closed = false;
  const input = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (quoted) {
      if (c === '"') {
        if (input[i + 1] === '"') {
          value += '"';
          i++;
        } else {
          quoted = false;
          closed = true;
        }
      } else value += c;
    } else if (c === "," || c === "\n" || c === "\r") {
      row.push(value);
      value = "";
      closed = false;
      if (c !== ",") {
        records.push(row);
        row = [];
        if (c === "\r" && input[i + 1] === "\n") i++;
      }
    } else if (c === '"' && value === "" && !closed) quoted = true;
    else if (closed || c === '"')
      return fail(
        "Invalid CSV quoting. Put commas and line breaks inside double quotes.",
      );
    else value += c;
  }
  if (quoted) return fail("An opening quote is missing its closing quote.");
  if (row.length || value || closed) {
    row.push(value);
    records.push(row);
  }
  const populated = records.filter((r) => r.some((cell) => cell.trim()));
  if (!populated.length)
    return fail(
      "This file is empty. Add a header row and at least one prospect.",
    );
  if (populated.length > 501)
    return fail("Import up to 500 prospects at a time.");
  const aliases: Record<string, string> = {
    name: "name",
    fullname: "name",
    company: "company",
    companyname: "company",
    role: "role",
    title: "role",
    jobtitle: "role",
    phone: "phone",
    phonenumber: "phone",
    notes: "notes",
  };
  const headers = populated[0].map(
    (h) => aliases[h.trim().toLowerCase().replace(/[ _-]/g, "")] ?? "",
  );
  if (["name", "company", "role"].some((h) => !headers.includes(h)))
    return fail(
      "Required columns: name, company, role (or title). Optional: phone, notes.",
    );
  const recognized = headers.filter(Boolean);
  if (new Set(recognized).size !== recognized.length)
    return fail(
      "Two columns map to the same field. Keep one name, company, role, phone, and notes column.",
    );
  const result: CsvResult = {
    rows: [],
    errors: [],
    total: populated.length - 1,
  };
  populated.slice(1).forEach((r, index) => {
    if (r.length !== headers.length) {
      result.errors.push(
        `Record ${index + 2}: expected ${headers.length} columns, found ${r.length}.`,
      );
      return;
    }
    const record: Record<string, string> = { phone: "", notes: "" };
    headers.forEach((h, i) => {
      if (h) record[h] = r[i];
    });
    const parsed = prospectInputSchema.safeParse(record);
    if (parsed.success) result.rows.push(parsed.data);
    else
      result.errors.push(
        `Record ${index + 2}: ${parsed.error.issues.map((issue) => `${String(issue.path[0])} — ${issue.message}`).join("; ")}`,
      );
  });
  if (!result.total)
    result.errors.push("The file has headers but no prospects.");
  return result;
}

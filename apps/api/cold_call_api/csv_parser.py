"""CSV parser and validator for calling lists (Lane C).

Handles:
- UTF-8 BOM
- Strict quoting (RFC 4180)
- Multiline notes and embedded quotes/commas
- Header alias resolution
- Max size and row limits (up to 500 rows)
- Per-row validation preserving valid records
"""

from __future__ import annotations

import io
from typing import NamedTuple
from cold_call_api.models import ProspectInput


MAX_CSV_BYTES = 1_000_000


class CsvParseResult(NamedTuple):
    rows: list[ProspectInput]
    errors: list[str]  # file-level problems
    total: int
    row_errors: list[tuple[int, str]] = []  # (file line number, short message)


def _field_message(err: Exception) -> str:
    """Short field-level message. Never echoes the submitted value."""
    details = getattr(err, "errors", None)
    if not callable(details):
        return "Row is invalid."
    parts: list[str] = []
    for d in details():
        field = str(d["loc"][0]) if d.get("loc") else "row"
        kind = d.get("type", "")
        if kind == "string_too_short":
            parts.append(f"{field} is required")
        elif kind == "string_too_long":
            parts.append(f"{field} is too long (max {d.get('ctx', {}).get('max_length', '?')} characters)")
        else:
            parts.append(f"{field} is invalid")
    return "; ".join(parts) + "." if parts else "Row is invalid."


def parse_prospect_csv(text: str) -> CsvParseResult:
    """Parse CSV text into ProspectInput objects with comprehensive error reporting."""
    if len(text) > MAX_CSV_BYTES:
        return CsvParseResult(rows=[], errors=["Choose a CSV smaller than 1 MB."], total=0)

    # Strip UTF-8 BOM
    input_text = text.lstrip("\ufeff")

    # Custom RFC 4180 tokenizer to accurately match edge cases
    records: list[tuple[int, list[str]]] = []  # (starting file line, cells)
    line = 1
    row_start = 1
    current_row: list[str] = []
    current_val: list[str] = []
    quoted = False
    closed = False

    i = 0
    n = len(input_text)
    while i < n:
        c = input_text[i]
        if quoted:
            if c == '"':
                if i + 1 < n and input_text[i + 1] == '"':
                    current_val.append('"')
                    i += 1
                else:
                    quoted = False
                    closed = True
            else:
                if c == "\n" or (c == "\r" and input_text[i + 1 : i + 2] != "\n"):
                    line += 1
                current_val.append(c)
        elif c in (",", "\n", "\r"):
            current_row.append("".join(current_val))
            current_val = []
            closed = False
            if c != ",":
                records.append((row_start, current_row))
                current_row = []
                if c == "\r" and i + 1 < n and input_text[i + 1] == "\n":
                    i += 1
                line += 1
                row_start = line
        elif c == '"' and not current_val and not closed:
            quoted = True
        elif closed or c == '"':
            return CsvParseResult(
                rows=[],
                errors=["Invalid CSV quoting. Put commas and line breaks inside double quotes."],
                total=0,
            )
        else:
            current_val.append(c)
        i += 1

    if quoted:
        return CsvParseResult(
            rows=[],
            errors=["An opening quote is missing its closing quote."],
            total=0,
        )

    if current_row or current_val or closed:
        current_row.append("".join(current_val))
        records.append((row_start, current_row))

    populated = [(ln, r) for ln, r in records if any(cell.strip() for cell in r)]
    if not populated:
        return CsvParseResult(
            rows=[],
            errors=["This file is empty. Add a header row and at least one prospect."],
            total=0,
        )

    if len(populated) > 501:
        return CsvParseResult(
            rows=[],
            errors=["Import up to 500 prospects at a time."],
            total=0,
        )

    aliases = {
        "name": "name",
        "fullname": "name",
        "prospect": "name",
        "prospectname": "name",
        "company": "company",
        "companyname": "company",
        "account": "company",
        "organization": "company",
        "role": "role",
        "title": "role",
        "jobtitle": "role",
        "position": "role",
        "phone": "phone",
        "phonenumber": "phone",
        "telephone": "phone",
        "notes": "notes",
        "note": "notes",
        "comments": "notes",
    }

    raw_headers = populated[0][1]
    headers: list[str] = []
    for h in raw_headers:
        norm = h.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        headers.append(aliases.get(norm, ""))

    if not all(k in headers for k in ("name", "company", "role")):
        return CsvParseResult(
            rows=[],
            errors=["Required columns: name, company, role (or title). Optional: phone, notes."],
            total=0,
        )

    recognized = [h for h in headers if h]
    if len(set(recognized)) != len(recognized):
        return CsvParseResult(
            rows=[],
            errors=["Two columns map to the same field. Keep one name, company, role, phone, and notes column."],
            total=0,
        )

    valid_rows: list[ProspectInput] = []
    row_errors: list[tuple[int, str]] = []
    file_errors: list[str] = []
    total_data_rows = len(populated) - 1

    for row_num, r in populated[1:]:
        if len(r) != len(headers):
            row_errors.append((row_num, f"expected {len(headers)} columns, found {len(r)}."))
            continue

        raw_dict: dict[str, str] = {"phone": "", "notes": ""}
        for h, val in zip(headers, r):
            if h:
                raw_dict[h] = val

        try:
            parsed = ProspectInput.model_validate(raw_dict)
            valid_rows.append(parsed)
        except Exception as err:
            row_errors.append((row_num, _field_message(err)))

    if total_data_rows == 0:
        file_errors.append("The file has headers but no prospects.")

    return CsvParseResult(rows=valid_rows, errors=file_errors, total=total_data_rows, row_errors=row_errors)

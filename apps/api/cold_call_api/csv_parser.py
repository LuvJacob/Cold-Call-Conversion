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


class CsvParseResult(NamedTuple):
    rows: list[ProspectInput]
    errors: list[str]
    total: int


def parse_prospect_csv(text: str) -> CsvParseResult:
    """Parse CSV text into ProspectInput objects with comprehensive error reporting."""
    if len(text) > 1_000_000:
        return CsvParseResult(rows=[], errors=["Choose a CSV smaller than 1 MB."], total=0)

    # Strip UTF-8 BOM
    input_text = text.lstrip("\ufeff")

    # Custom RFC 4180 tokenizer to accurately match edge cases
    records: list[list[str]] = []
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
                current_val.append(c)
        elif c in (",", "\n", "\r"):
            current_row.append("".join(current_val))
            current_val = []
            closed = False
            if c != ",":
                records.append(current_row)
                current_row = []
                if c == "\r" and i + 1 < n and input_text[i + 1] == "\n":
                    i += 1
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
        records.append(current_row)

    populated = [r for r in records if any(cell.strip() for cell in r)]
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

    raw_headers = populated[0]
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
    row_errors: list[str] = []
    total_data_rows = len(populated) - 1

    for idx, r in enumerate(populated[1:]):
        row_num = idx + 2
        if len(r) != len(headers):
            row_errors.append(f"Record {row_num}: expected {len(headers)} columns, found {len(r)}.")
            continue

        raw_dict: dict[str, str] = {"phone": "", "notes": ""}
        for h, val in zip(headers, r):
            if h:
                raw_dict[h] = val

        try:
            parsed = ProspectInput.model_validate(raw_dict)
            valid_rows.append(parsed)
        except Exception as err:
            row_errors.append(f"Record {row_num}: {err}")

    if total_data_rows == 0:
        row_errors.append("The file has headers but no prospects.")

    return CsvParseResult(rows=valid_rows, errors=row_errors, total=total_data_rows)

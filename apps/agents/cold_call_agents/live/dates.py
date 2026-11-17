"""Shared date parsing for provider date formats.

Every provider date goes through `parse_date` before it reaches a `Source`:
the result is ISO `YYYY-MM-DD` or None (undated). Never raises.

Handled: ISO dates and datetimes (with `Z` or an offset), RFC 2822
("Fri, 03 May 2024 10:00:00 GMT"), "2024-05" and "2024" (first day of the
period), "May 3, 2024" / "3 May 2024" / "May 2024", and epoch seconds or
milliseconds (int, float or digit string).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_YM = re.compile(r"^(\d{4})-(\d{1,2})$")
_Y = re.compile(r"^(\d{4})$")
_MDY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
_DMY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$")
_MY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$")


def _make(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _month(name: str) -> Optional[int]:
    return _MONTHS.get(name[:3].lower())


def _epoch(n: float) -> Optional[str]:
    if n > 1e11:  # milliseconds
        n /= 1000
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def parse_date(value: Any) -> Optional[str]:
    """Return ISO YYYY-MM-DD, or None when the value is missing or unrecognised."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch(float(value)) if value > 0 else None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if re.fullmatch(r"\d{9,13}(\.\d+)?", s):
        return _epoch(float(s))
    if m := _Y.match(s):
        return _make(int(m[1]), 1, 1)
    if m := _YM.match(s):
        return _make(int(m[1]), int(m[2]), 1)
    if m := _MDY.match(s):
        mo = _month(m[1])
        return _make(int(m[3]), mo, int(m[2])) if mo else None
    if m := _DMY.match(s):
        mo = _month(m[2])
        return _make(int(m[3]), mo, int(m[1])) if mo else None
    if m := _MY.match(s):
        mo = _month(m[1])
        return _make(int(m[2]), mo, 1) if mo else None
    try:  # ISO date or datetime ("Z" is accepted by fromisoformat on 3.11+)
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError:
        pass
    try:  # RFC 2822
        dt = parsedate_to_datetime(s)
        return dt.date().isoformat() if dt else None
    except (TypeError, ValueError, IndexError):
        return None

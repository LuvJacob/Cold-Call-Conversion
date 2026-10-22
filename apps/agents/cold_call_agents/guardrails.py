"""Guardrails (v0: simple regex/keyword rules, not a complete privacy filter)."""

from __future__ import annotations

import re

from .models import Fact, Source

# Phone numbers: international (+44 20 7946 0958), UK trunk ((020) 7946 0958),
# NANP (415-555-1234) and unseparated 10-15 digit runs (4155551234).
PHONES = [
    re.compile(r"\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}"),
    re.compile(r"\(0\d{2,4}\)[\s.-]?\d{3,4}[\s.-]?\d{3,4}"),
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?!\d)"),
    re.compile(r"(?<![\d.,$])\d{10,15}(?!\d)"),
]
ADDRESSES = [
    re.compile(
        r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Za-z]+\s){1,3}"
        r"(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|court|ct|boulevard|blvd|way)\b",
        re.I,
    ),
    re.compile(r"\b\d{1,5}[A-Za-z]?,?\s+(?:rue|via|calle|allee|chemin)\s+[A-Za-z' ]{1,30}", re.I),
    re.compile(r"\b(?:apt|apartment|flat)\.?\s*#?\d+[A-Za-z]?\b", re.I),
]
_PERSONAL_DOMAINS = (
    "gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|icloud|me|mac|aol|"
    "proton|protonmail|gmx|mail|zoho|yandex"
)
PERSONAL_EMAIL = re.compile(
    rf"[\w.+-]+@(?:{_PERSONAL_DOMAINS})\.(?:com|net|org|de|fr|co\.uk|[a-z]{{2,3}})\b", re.I
)
FAMILY = re.compile(
    r"\b(wife|husband|spouse|married|marriage|divorced|children|daughter|son|kids|"
    r"girlfriend|boyfriend|family members?)\b",
    re.I,
)
INSTRUCTION_LIKE = re.compile(
    r"(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,30}"
    r"\b(instructions?|prompts?|rules)|system prompt|you are now|act as (a|an|the)\b"
    r"|\bdisregard\b.{0,20}\b(above|previous|prior|earlier)\b|\bnew instructions?\b",
    re.I,
)
ROLE_PREFIX = re.compile(r"^\W*(system|assistant|user|developer)\s*:", re.I)
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.I | re.S)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_REMOVED = "[removed: private]"


def is_private(text: str) -> bool:
    return any(p.search(text) for p in [*PHONES, *ADDRESSES, PERSONAL_EMAIL, FAMILY])


def redact_private(text: str) -> str:
    """Replace phone numbers, street addresses and personal emails with a marker."""
    for p in [*PHONES, *ADDRESSES, PERSONAL_EMAIL]:
        text = p.sub(_REMOVED, text)
    return text


def drop_private(facts: list[Fact]) -> list[Fact]:
    """Remove facts that contain private personal data (v0 rules)."""
    return [f for f in facts if not is_private(f"{f.text} {f.value}")]


def sanitize_web_text(text: str, max_chars: int = 2000, redact: bool = False) -> str:
    """Make web text safe to treat as DATA.

    Strips HTML tags and control characters, removes instruction-like
    sentences, optionally redacts private data (and removes sentences about
    family), and truncates last. Callers must still pass the result to a model
    only inside a clearly delimited data block; web text is never instructions.
    """
    text = _TAGS.sub(" ", text)
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not (INSTRUCTION_LIKE.search(s) or ROLE_PREFIX.search(s))]
    if redact:
        kept = [redact_private(s) for s in kept if not FAMILY.search(s)]
    return " ".join(kept).strip()[:max_chars]


def escape_data(text: str) -> str:
    """Make text safe inside a <data> block: it can't contain tag delimiters."""
    return text.replace("<", "‹").replace(">", "›")


def require_sources(facts: list[Fact], sources: list[Source]) -> list[Fact]:
    """Drop facts with no valid source id; trim invalid ids from the rest."""
    valid = {s.id for s in sources}
    kept = []
    for f in facts:
        ids = [i for i in f.source_ids if i in valid]
        if ids:
            kept.append(f.model_copy(update={"source_ids": ids}))
    return kept

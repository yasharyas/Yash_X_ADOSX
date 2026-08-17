"""Shared parsing helpers for dirty CSV values.

These live in their own module (not inside the importer or the models) because
the same normalization has to be reused by the importer AND the tests. Keeping
them as small, side-effect-free functions means they can be unit tested in
isolation without a database, and reused anywhere a raw string needs cleaning.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


# Compiled once at module load rather than on every call: normalize_record_ref
# runs once per System B row on import, and compiling the pattern ahead of time
# avoids re-parsing the regex 121+ times. Case-insensitive so "rec" and "REC" match.
_REC_PATTERN = re.compile(r"REC-?(\d+)", re.IGNORECASE)


def normalize_record_ref(raw: Optional[str]) -> Optional[str]:
    """Turn a messy System B ``record_ref`` into a canonical System A ``record_id``.

    Why this exists: System B's reference column is deliberately dirty. The same
    real record shows up as ``REC-1034``, ``rec1034``, ``' REC - 1070 '`` and even
    a bare ``1112``. If we matched on the raw string, every one of those clean-but-
    ugly rows would be miscounted as an "orphan" or "missing" disagreement. This
    function collapses all the accepted spellings to one form (``REC-<digits>``)
    so matching is done on identity, not on formatting.

    Why it returns ``None`` instead of raising: an un-normalizable ref is itself a
    meaningful signal (a genuine orphan), so the caller decides what to do with it.
    Raising would force the importer to wrap every call in try/except and risk
    dropping the row, which the brief forbids.

    Accepts: ``REC-1034``, ``rec1034``, ``' REC - 1070 '``, bare ``'1112'``.
    Returns ``None`` when nothing usable can be extracted.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # Strip *all* internal whitespace first so "REC - 1070" becomes "REC-1070".
    # Done before the regex because the pattern intentionally has no room for
    # spaces; normalizing whitespace here keeps the pattern simple.
    compact = re.sub(r"\s+", "", text)
    match = _REC_PATTERN.search(compact)
    if match:
        # Rebuild from the captured digits so the prefix/casing/hyphen are
        # always identical regardless of how the input was written.
        return f"REC-{match.group(1)}"

    # A bare number like "1112" has no REC prefix but is clearly the numeric part
    # of a record id, so we reattach the canonical prefix rather than discard it.
    if compact.isdigit():
        return f"REC-{compact}"

    return None


def parse_decimal(raw: Optional[str]) -> tuple[Optional[Decimal], list[str]]:
    """Parse a money-like string into a ``Decimal``, reporting why if it fails.

    Why ``Decimal`` and not ``float``: these are monetary values and equality is
    the whole point of the comparison. Floats would introduce rounding error
    (e.g. ``0.1 + 0.2``), which could turn two genuinely-equal values into a false
    "value mismatch". ``Decimal`` compares exactly.

    Why it returns a ``(value, issues)`` tuple instead of raising: the importer
    must keep every row even when a number is garbage. Returning ``None`` plus a
    machine-readable issue code lets the row be stored with a null parsed value
    and an audit trail, instead of blowing up the whole import.

    Why we strip commas: one row uses Indian-style grouping (``1,25,400.00``).
    Stripping every comma handles both that and Western thousands separators
    without needing locale detection.
    """
    issues: list[str] = []
    if raw is None:
        return None, ["BLANK_VALUE"]

    text = str(raw).strip()
    if text == "":
        # Distinguished from garbage so downstream code / audits can tell an
        # empty cell apart from an un-parseable one.
        return None, ["BLANK_VALUE"]

    cleaned = text.replace(",", "")
    try:
        return Decimal(cleaned), issues
    except (InvalidOperation, ValueError):
        # Any non-numeric leftover (letters, symbols) lands here. We swallow the
        # exception on purpose so the caller can persist the raw text untouched.
        return None, ["UNPARSEABLE_NUMBER"]


def parse_date(raw: Optional[str]) -> tuple[Optional[date], list[str]]:
    """Parse a date string, trying the formats that actually appear in the data.

    Why several formats: the dataset is a "real export", so a date could be ISO
    (``2026-03-20``) or day/month/year or month/day/year. We try the most likely
    orderings and take the first that works, rather than assuming one format and
    silently corrupting the rest.

    Why the same ``(value, issues)`` contract as :func:`parse_decimal`: dates are
    not part of the required disagreement checks, but we still parse and store
    them without ever dropping a row, so the importer treats every parsed field
    the same way.
    """
    if raw is None:
        return None, ["BLANK_DATE"]
    text = str(raw).strip()
    if text == "":
        return None, ["BLANK_DATE"]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date(), []
        except ValueError:
            # Wrong format for this candidate; try the next one rather than fail.
            continue
    return None, ["UNPARSEABLE_DATE"]

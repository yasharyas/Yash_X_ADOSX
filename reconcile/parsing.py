"""Shared parsing helpers for dirty CSV values."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


_REC_PATTERN = re.compile(r"REC-?(\d+)", re.IGNORECASE)


def normalize_record_ref(raw: Optional[str]) -> Optional[str]:
    """
    Turn messy System B refs into System A style ids.

    Accepts: REC-1034, rec1034, ' REC - 1070 ', bare '1112'.
    Returns None when nothing usable can be extracted.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    compact = re.sub(r"\s+", "", text)
    match = _REC_PATTERN.search(compact)
    if match:
        return f"REC-{match.group(1)}"

    # Bare numeric id like "1112"
    if compact.isdigit():
        return f"REC-{compact}"

    return None


def parse_decimal(raw: Optional[str]) -> tuple[Optional[Decimal], list[str]]:
    """
    Parse a money-like number. Strips thousands separators (including Indian-style commas).
    Blank -> (None, ['BLANK_VALUE']); garbage -> (None, ['UNPARSEABLE_NUMBER']).
    """
    issues: list[str] = []
    if raw is None:
        return None, ["BLANK_VALUE"]

    text = str(raw).strip()
    if text == "":
        return None, ["BLANK_VALUE"]

    cleaned = text.replace(",", "")
    try:
        return Decimal(cleaned), issues
    except (InvalidOperation, ValueError):
        return None, ["UNPARSEABLE_NUMBER"]


def parse_date(raw: Optional[str]) -> tuple[Optional[date], list[str]]:
    if raw is None:
        return None, ["BLANK_DATE"]
    text = str(raw).strip()
    if text == "":
        return None, ["BLANK_DATE"]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date(), []
        except ValueError:
            continue
    return None, ["UNPARSEABLE_DATE"]

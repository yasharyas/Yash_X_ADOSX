"""
Comparison logic: match System A records to System B entries and flag disagreements.

This module is intentionally pure over plain data so tests do not need the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional, Sequence

logger = logging.getLogger("reconcile.compare")


REASON_MISSING_IN_B = "missing_in_b"
REASON_ORPHAN_IN_B = "orphan_in_b"
REASON_DUPLICATE_IN_B = "duplicate_in_b"
REASON_VALUE_MISMATCH = "value_mismatch"

ALL_REASONS = (
    REASON_MISSING_IN_B,
    REASON_ORPHAN_IN_B,
    REASON_DUPLICATE_IN_B,
    REASON_VALUE_MISMATCH,
)


@dataclass(frozen=True)
class ARecord:
    """A minimal, DB-free view of a System A record used by the comparison.

    Why a dataclass instead of passing the Django model: the comparison logic
    should not depend on the ORM. Using a plain, ``frozen`` (immutable) dataclass
    lets tests construct fixtures in one line and guarantees the comparison never
    accidentally mutates its input. Only the fields the algorithm needs live here.
    """

    record_id: str
    location_id: str
    total_value: Optional[Decimal]
    total_value_raw: str = ""


@dataclass(frozen=True)
class BEntry:
    """A DB-free view of a System B entry.

    Why it carries both ``record_ref_raw`` and ``record_id_normalized``: the
    normalized id is what we match on, but keeping the raw ref lets us explain
    *why* an entry is an orphan (bad reference) when reporting to the user.
    """

    entry_id: str
    record_ref_raw: str
    record_id_normalized: Optional[str]
    location_id: str
    value: Optional[Decimal]
    value_raw: str = ""


@dataclass(frozen=True)
class Disagreement:
    """One reported disagreement, shaped for direct display in the table.

    Why a dedicated result type instead of a dict: it documents exactly what a
    disagreement contains, gives the API a stable contract, and makes the tests
    assert on named fields rather than fragile dict keys. It holds both parsed
    (``a_value``) and raw (``a_value_raw``) values so the UI can show the human
    the original text while sorting/comparison uses the parsed number.
    """

    reason: str
    record_id: Optional[str]
    location_id: str
    org_id: Optional[str]
    a_value: Optional[Decimal]
    a_value_raw: Optional[str]
    b_value: Optional[Decimal]
    b_value_raw: Optional[str]
    b_entry_ids: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""


def _values_agree(a: Optional[Decimal], b: Optional[Decimal]) -> bool:
    """Decide whether two parsed values count as "the same".

    Why it is its own function: the null-handling rule is subtle and easy to get
    wrong inline. Two missing values agree (nothing to disagree about), but a
    value present on one side and absent on the other is a real disagreement
    (e.g. System B's blank ``value`` for ``REC-1050`` vs System A's number). Naming
    the rule keeps :func:`find_disagreements` readable and testable.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a == b


def find_disagreements(
    a_records: Sequence[ARecord],
    b_entries: Sequence[BEntry],
    location_org: dict[str, str],
    *,
    org_id: Optional[str] = None,
) -> list[Disagreement]:
    """Return every disagreement between System A and System B.

    Why this is the single source of truth: the whole take-home hinges on this
    decision, so it is one pure function with no I/O. Both the API and the tests
    call it, which means a test that passes proves the behavior the API ships.

    How it works and why in this order:
      1. Index B by normalized id so each A record is a dict lookup, not a scan
         over all B rows (clearer, and O(1) per record instead of O(n)).
      2. Walk A records first to catch missing / duplicate / value disagreements.
      3. Then walk B entries to catch orphans (B pointing at a non-existent A).
      4. Finally apply the tenant filter, so the org scope is enforced in exactly
         one place rather than being threaded through every branch above.

    Tenant isolation: when ``org_id`` is set, only disagreements whose scoping
    location belongs to that org are returned, so one tenant can never see
    another's rows.
    """
    # Index both sides once up front. a_by_id lets the orphan pass ask "does this
    # A record exist?" cheaply; b_by_norm groups B entries per record so a count
    # of >1 immediately reveals a duplicate.
    a_by_id = {r.record_id: r for r in a_records}
    b_by_norm: dict[Optional[str], list[BEntry]] = {}
    for entry in b_entries:
        b_by_norm.setdefault(entry.record_id_normalized, []).append(entry)

    results: list[Disagreement] = []

    for record in a_records:
        matches = b_by_norm.get(record.record_id, [])
        org = location_org.get(record.location_id)

        if len(matches) == 0:
            results.append(
                Disagreement(
                    reason=REASON_MISSING_IN_B,
                    record_id=record.record_id,
                    location_id=record.location_id,
                    org_id=org,
                    a_value=record.total_value,
                    a_value_raw=record.total_value_raw,
                    b_value=None,
                    b_value_raw=None,
                    b_entry_ids=(),
                    detail="System A record has no System B entry",
                )
            )
            continue

        if len(matches) > 1:
            b_values = [m.value for m in matches]
            b_raws = [m.value_raw for m in matches]
            results.append(
                Disagreement(
                    reason=REASON_DUPLICATE_IN_B,
                    record_id=record.record_id,
                    location_id=record.location_id,
                    org_id=org,
                    a_value=record.total_value,
                    a_value_raw=record.total_value_raw,
                    b_value=b_values[0] if len(set(b_values)) == 1 else None,
                    b_value_raw="; ".join(b_raws),
                    b_entry_ids=tuple(m.entry_id for m in matches),
                    detail=f"{len(matches)} System B entries for the same record",
                )
            )
            continue

        only = matches[0]
        if not _values_agree(record.total_value, only.value):
            results.append(
                Disagreement(
                    reason=REASON_VALUE_MISMATCH,
                    record_id=record.record_id,
                    location_id=record.location_id,
                    org_id=org,
                    a_value=record.total_value,
                    a_value_raw=record.total_value_raw,
                    b_value=only.value,
                    b_value_raw=only.value_raw,
                    b_entry_ids=(only.entry_id,),
                    detail="System A total_value differs from System B value",
                )
            )

    seen_orphan_keys: set[str] = set()
    for entry in b_entries:
        norm = entry.record_id_normalized
        # Orphan: normalized id missing from A, or could not be normalized at all.
        if norm is not None and norm in a_by_id:
            continue
        key = entry.entry_id
        if key in seen_orphan_keys:
            continue
        seen_orphan_keys.add(key)
        org = location_org.get(entry.location_id)
        results.append(
            Disagreement(
                reason=REASON_ORPHAN_IN_B,
                record_id=norm,
                location_id=entry.location_id,
                org_id=org,
                a_value=None,
                a_value_raw=None,
                b_value=entry.value,
                b_value_raw=entry.value_raw,
                b_entry_ids=(entry.entry_id,),
                detail=(
                    "System B entry points at a record that does not exist in System A"
                    if norm
                    else "System B record_ref could not be normalized"
                ),
            )
        )

    if org_id is not None:
        before = len(results)
        results = [d for d in results if d.org_id == org_id]
        logger.debug(
            "find_disagreements: filtered %d -> %d for org_id=%r",
            before,
            len(results),
            org_id,
        )
    else:
        logger.debug("find_disagreements: %d disagreements (no org filter)", len(results))

    return results


def disagreements_from_queryset(
    a_qs: Iterable,
    b_qs: Iterable,
    locations_qs: Iterable,
    *,
    org_id: Optional[str] = None,
) -> list[Disagreement]:
    """Adapt Django model instances into the pure inputs of ``find_disagreements``.

    Why this adapter exists: it is the seam between "Django world" (querysets,
    model instances) and the "pure world" (plain dataclasses). Keeping the
    translation here means :func:`find_disagreements` never imports Django and
    stays trivially testable, while the view stays thin and just hands over
    querysets. The ``location_org`` map is built once so the org lookup inside
    the algorithm is a dict access rather than a query per row.
    """
    location_org = {loc.location_id: loc.org_id for loc in locations_qs}
    a_records = [
        ARecord(
            record_id=r.record_id,
            location_id=r.location_id,
            total_value=r.total_value,
            total_value_raw=r.total_value_raw,
        )
        for r in a_qs
    ]
    b_entries = [
        BEntry(
            entry_id=e.entry_id,
            record_ref_raw=e.record_ref_raw,
            record_id_normalized=e.record_id_normalized,
            location_id=e.location_id,
            value=e.value,
            value_raw=e.value_raw,
        )
        for e in b_qs
    ]
    return find_disagreements(a_records, b_entries, location_org, org_id=org_id)

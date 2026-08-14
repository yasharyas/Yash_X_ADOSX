"""CSV import: every row becomes a DB row; parse failures never drop data."""

from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from .models import Location, SystemARecord, SystemBEntry
from .parsing import normalize_record_ref, parse_date, parse_decimal


def _cell(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    return str(value)


def import_locations(path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            Location.objects.update_or_create(
                location_id=_cell(row, "location_id"),
                defaults={
                    "org_id": _cell(row, "org_id"),
                    "location_name": _cell(row, "location_name"),
                },
            )
            count += 1
    return count


def import_system_a(path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            issues: list[str] = []
            base, base_issues = parse_decimal(_cell(row, "base_value"))
            adj, adj_issues = parse_decimal(_cell(row, "adjustment"))
            total, total_issues = parse_decimal(_cell(row, "total_value"))
            event_date, date_issues = parse_date(_cell(row, "event_date"))
            issues.extend(f"base_value:{i}" for i in base_issues)
            issues.extend(f"adjustment:{i}" for i in adj_issues)
            issues.extend(f"total_value:{i}" for i in total_issues)
            issues.extend(f"event_date:{i}" for i in date_issues)

            SystemARecord.objects.update_or_create(
                record_id=_cell(row, "record_id"),
                defaults={
                    "location_id": _cell(row, "location_id"),
                    "event_date_raw": _cell(row, "event_date"),
                    "category_code": _cell(row, "category_code"),
                    "actor_id": _cell(row, "actor_id"),
                    "base_value_raw": _cell(row, "base_value"),
                    "adjustment_raw": _cell(row, "adjustment"),
                    "total_value_raw": _cell(row, "total_value"),
                    "state": _cell(row, "state"),
                    "event_date": event_date,
                    "base_value": base,
                    "adjustment": adj,
                    "total_value": total,
                    "parse_issues": issues,
                },
            )
            count += 1
    return count


def import_system_b(path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            issues: list[str] = []
            ref_raw = _cell(row, "record_ref")
            normalized = normalize_record_ref(ref_raw)
            if normalized is None and ref_raw.strip():
                issues.append("record_ref:UNPARSEABLE_REF")
            elif normalized is None:
                issues.append("record_ref:BLANK_REF")

            value, value_issues = parse_decimal(_cell(row, "value"))
            recorded_on, date_issues = parse_date(_cell(row, "recorded_on"))
            issues.extend(f"value:{i}" for i in value_issues)
            issues.extend(f"recorded_on:{i}" for i in date_issues)

            SystemBEntry.objects.update_or_create(
                entry_id=_cell(row, "entry_id"),
                defaults={
                    "record_ref_raw": ref_raw,
                    "record_id_normalized": normalized,
                    "location_id": _cell(row, "location_id"),
                    "recorded_on_raw": _cell(row, "recorded_on"),
                    "value_raw": _cell(row, "value"),
                    "label": _cell(row, "label"),
                    "recorded_on": recorded_on,
                    "value": value,
                    "parse_issues": issues,
                },
            )
            count += 1
    return count


@transaction.atomic
def import_all(data_dir: Path | None = None) -> dict[str, int]:
    """Wipe and reload all three CSVs. Never skips a CSV row."""
    root = Path(data_dir) if data_dir else Path(settings.DATA_DIR)
    SystemBEntry.objects.all().delete()
    SystemARecord.objects.all().delete()
    Location.objects.all().delete()

    return {
        "locations": import_locations(root / "locations.csv"),
        "system_a": import_system_a(root / "system_a.csv"),
        "system_b": import_system_b(root / "system_b.csv"),
    }

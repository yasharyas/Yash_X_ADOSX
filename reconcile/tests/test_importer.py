"""Tests that dirty rows survive the importer and nothing is silently dropped.

These write deliberately awful CSVs to a temp directory rather than relying on the
bundled dataset, because the brief warns that "real exports are worse" - the
importer has to hold up against mess the sample files do not contain.
"""

import csv
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from reconcile.importer import import_all, import_system_a, import_system_b
from reconcile.models import ImportAnomaly, Location, SystemARecord, SystemBEntry


A_HEADER = [
    "record_id",
    "location_id",
    "event_date",
    "category_code",
    "actor_id",
    "base_value",
    "adjustment",
    "total_value",
    "state",
]
B_HEADER = ["entry_id", "record_ref", "location_id", "recorded_on", "value", "label"]
L_HEADER = ["location_id", "org_id", "location_name"]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


class ImporterSurvivesDirtyRowsTests(TestCase):
    """A bad *value* must never cost us the row."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        write_csv(self.dir / "locations.csv", L_HEADER, [["LOC-101", "ORG-A", "Location 101"]])

    def test_unparseable_and_blank_values_still_produce_rows(self):
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [
                # blank actor, garbage number, blank total, bad date - all still rows
                ["REC-1", "LOC-101", "2026-03-01", "CAT-01", "", "10.00", "1.00", "11.00", "CONFIRMED"],
                ["REC-2", "LOC-101", "2026-03-02", "CAT-02", "USR-1", "abc", "1.00", "", "CONFIRMED"],
                ["REC-3", "LOC-101", "not-a-date", "CAT-03", "USR-2", "5.00", "1.00", "6.00", "VOIDED"],
            ],
        )
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        result = import_all(self.dir)

        self.assertEqual(SystemARecord.objects.count(), 3)
        self.assertEqual(result["system_a"].rows_read, 3)
        self.assertEqual(result["system_a"].rows_stored, 3)
        self.assertEqual(result["system_a"].quarantined, 0)

    def test_raw_text_is_preserved_even_when_parsing_fails(self):
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [["REC-2", "LOC-101", "2026-03-02", "CAT-02", "USR-1", "abc", "1.00", "", "CONFIRMED"]],
        )
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        import_all(self.dir)
        record = SystemARecord.objects.get(record_id="REC-2")

        # Parsed fields are null, but the original export text is still readable.
        self.assertIsNone(record.base_value)
        self.assertIsNone(record.total_value)
        self.assertEqual(record.base_value_raw, "abc")
        self.assertIn("base_value:UNPARSEABLE_NUMBER", record.parse_issues)
        self.assertIn("total_value:BLANK_VALUE", record.parse_issues)

    def test_grouped_number_is_parsed_and_raw_kept(self):
        write_csv(self.dir / "system_a.csv", A_HEADER, [])
        write_csv(
            self.dir / "system_b.csv",
            B_HEADER,
            [["ENT-1", "REC-1", "LOC-101", "2026-03-01", "1,25,400.00", "x"]],
        )

        import_all(self.dir)
        entry = SystemBEntry.objects.get(entry_id="ENT-1")

        self.assertEqual(entry.value, Decimal("125400.00"))
        self.assertEqual(entry.value_raw, "1,25,400.00")

    def test_dirty_refs_are_normalized_at_import(self):
        write_csv(self.dir / "system_a.csv", A_HEADER, [])
        write_csv(
            self.dir / "system_b.csv",
            B_HEADER,
            [
                ["ENT-1", "rec1034", "LOC-101", "2026-03-01", "1.00", "x"],
                ["ENT-2", " REC - 1070 ", "LOC-101", "2026-03-01", "1.00", "x"],
                ["ENT-3", "1112", "LOC-101", "2026-03-01", "1.00", "x"],
                ["ENT-4", "garbage", "LOC-101", "2026-03-01", "1.00", "x"],
            ],
        )

        import_all(self.dir)

        self.assertEqual(SystemBEntry.objects.count(), 4)
        self.assertEqual(SystemBEntry.objects.get(entry_id="ENT-1").record_id_normalized, "REC-1034")
        self.assertEqual(SystemBEntry.objects.get(entry_id="ENT-2").record_id_normalized, "REC-1070")
        self.assertEqual(SystemBEntry.objects.get(entry_id="ENT-3").record_id_normalized, "REC-1112")
        # An unusable ref does not cost the row; it is kept and reported as an issue.
        unusable = SystemBEntry.objects.get(entry_id="ENT-4")
        self.assertIsNone(unusable.record_id_normalized)
        self.assertIn("record_ref:UNPARSEABLE_REF", unusable.parse_issues)

    def test_short_row_missing_trailing_columns_still_imports(self):
        path = self.dir / "system_a.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            handle.write(",".join(A_HEADER) + "\n")
            handle.write("REC-1,LOC-101,2026-03-01\n")  # truncated row
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        result = import_all(self.dir)

        self.assertEqual(result["system_a"].rows_stored, 1)
        self.assertEqual(SystemARecord.objects.get(record_id="REC-1").state, "")

    def test_utf8_bom_does_not_corrupt_the_first_column(self):
        path = self.dir / "system_a.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(A_HEADER)
            writer.writerow(
                ["REC-1", "LOC-101", "2026-03-01", "CAT-01", "USR-1", "1.00", "1.00", "2.00", "CONFIRMED"]
            )
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        import_all(self.dir)

        self.assertTrue(SystemARecord.objects.filter(record_id="REC-1").exists())


class NothingIsSilentlyDroppedTests(TestCase):
    """Rows whose natural key is unusable must be quarantined, not overwritten.

    This is the regression guard for a real bug: keying on the CSV's own identifier
    means a duplicate or blank key would otherwise collapse two source rows into
    one, while the importer still reported both as imported.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        write_csv(self.dir / "locations.csv", L_HEADER, [["LOC-101", "ORG-A", "Location 101"]])

    def test_duplicate_record_id_is_quarantined_not_overwritten(self):
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [
                ["REC-1", "LOC-101", "2026-03-01", "CAT-01", "USR-1", "10.00", "1.00", "11.00", "CONFIRMED"],
                ["REC-1", "LOC-101", "2026-03-02", "CAT-02", "USR-2", "99.00", "1.00", "100.00", "CONFIRMED"],
            ],
        )
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        result = import_all(self.dir)

        # The first row wins the key; the second is preserved in quarantine.
        self.assertEqual(SystemARecord.objects.count(), 1)
        self.assertEqual(SystemARecord.objects.get(record_id="REC-1").total_value, Decimal("11.00"))
        anomaly = ImportAnomaly.objects.get(source_file="system_a.csv")
        self.assertEqual(anomaly.reason, ImportAnomaly.REASON_DUPLICATE_SOURCE_KEY)
        self.assertEqual(anomaly.natural_key, "REC-1")
        # The losing row's data is still fully recoverable.
        self.assertEqual(anomaly.raw_row["total_value"], "100.00")
        self.assertEqual(result["system_a"].quarantined, 1)

    def test_duplicate_entry_id_is_quarantined(self):
        write_csv(self.dir / "system_a.csv", A_HEADER, [])
        write_csv(
            self.dir / "system_b.csv",
            B_HEADER,
            [
                ["ENT-1", "REC-1", "LOC-101", "2026-03-01", "11.00", "first"],
                ["ENT-1", "REC-1", "LOC-101", "2026-03-01", "999.00", "dup"],
            ],
        )

        import_all(self.dir)

        self.assertEqual(SystemBEntry.objects.count(), 1)
        self.assertEqual(
            ImportAnomaly.objects.get(source_file="system_b.csv").reason,
            ImportAnomaly.REASON_DUPLICATE_SOURCE_KEY,
        )

    def test_blank_primary_key_rows_are_each_quarantined(self):
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [
                ["", "LOC-101", "2026-03-03", "CAT-03", "USR-3", "5.00", "1.00", "6.00", "CONFIRMED"],
                ["", "LOC-101", "2026-03-04", "CAT-04", "USR-4", "7.00", "1.00", "8.00", "CONFIRMED"],
            ],
        )
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        import_all(self.dir)

        # Both survive separately, rather than collapsing into one empty-key row.
        self.assertEqual(SystemARecord.objects.count(), 0)
        self.assertEqual(
            ImportAnomaly.objects.filter(reason=ImportAnomaly.REASON_BLANK_PRIMARY_KEY).count(), 2
        )

    def test_every_row_read_is_accounted_for(self):
        """The invariant that makes "nothing dropped" checkable rather than a promise."""
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [
                ["REC-1", "LOC-101", "2026-03-01", "CAT-01", "USR-1", "10.00", "1.00", "11.00", "CONFIRMED"],
                ["REC-1", "LOC-101", "2026-03-02", "CAT-02", "USR-2", "99.00", "1.00", "100.00", "CONFIRMED"],
                ["", "LOC-101", "2026-03-03", "CAT-03", "USR-3", "abc", "1.00", "", "CONFIRMED"],
            ],
        )
        write_csv(
            self.dir / "system_b.csv",
            B_HEADER,
            [
                ["ENT-1", "REC-1", "LOC-101", "2026-03-01", "11.00", "x"],
                ["ENT-1", "REC-1", "LOC-101", "2026-03-01", "999.00", "dup"],
            ],
        )

        results = import_all(self.dir)

        for name, result in results.items():
            self.assertTrue(result.accounted_for, msg=f"{name}: {result}")
            self.assertEqual(result.rows_read, result.rows_stored + result.quarantined)

        stored = SystemARecord.objects.count() + SystemBEntry.objects.count() + Location.objects.count()
        quarantined = ImportAnomaly.objects.count()
        rows_read = sum(r.rows_read for r in results.values())
        self.assertEqual(rows_read, stored + quarantined)

    def test_duplicate_location_is_quarantined_to_avoid_ambiguous_tenancy(self):
        write_csv(
            self.dir / "locations.csv",
            L_HEADER,
            [
                ["LOC-101", "ORG-A", "Location 101"],
                ["LOC-101", "ORG-B", "Conflicting org"],
            ],
        )
        write_csv(self.dir / "system_a.csv", A_HEADER, [])
        write_csv(self.dir / "system_b.csv", B_HEADER, [])

        import_all(self.dir)

        # Tenancy must never be guessed: the first mapping stands, the clash is logged.
        self.assertEqual(Location.objects.get(location_id="LOC-101").org_id, "ORG-A")
        self.assertEqual(ImportAnomaly.objects.filter(source_file="locations.csv").count(), 1)


class ImportIsRepeatableTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        write_csv(self.dir / "locations.csv", L_HEADER, [["LOC-101", "ORG-A", "Location 101"]])
        write_csv(
            self.dir / "system_a.csv",
            A_HEADER,
            [["REC-1", "LOC-101", "2026-03-01", "CAT-01", "USR-1", "10.00", "1.00", "11.00", "CONFIRMED"]],
        )
        write_csv(
            self.dir / "system_b.csv",
            B_HEADER,
            [["ENT-1", "REC-1", "LOC-101", "2026-03-01", "11.00", "x"]],
        )

    def test_running_twice_does_not_duplicate_or_accumulate(self):
        """Wipe-and-reload has to be idempotent, including the quarantine table."""
        import_all(self.dir)
        import_all(self.dir)

        self.assertEqual(SystemARecord.objects.count(), 1)
        self.assertEqual(SystemBEntry.objects.count(), 1)
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(ImportAnomaly.objects.count(), 0)

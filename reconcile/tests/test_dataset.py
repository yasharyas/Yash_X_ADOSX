"""Golden-set regression test against the real bundled CSVs.

Why this file exists, and why it is the most important regression net here: the
unit tests in ``test_compare`` verify the rules against hand-built fixtures, but
they cannot catch a mistake in *which data is fed into* those rules. Pointing the
comparison at System A's ``base_value`` instead of ``total_value``, for example,
makes the app report 118 disagreements instead of 10 while every unit test still
passes.

This test pins the exact expected answer for the shipped dataset, so any change to
normalization, field selection, or tenant scoping fails loudly and specifically.
If the dataset is ever intentionally changed, these constants must be updated
deliberately - which is the point.
"""

from decimal import Decimal

from django.conf import settings
from django.test import TestCase

from reconcile.compare import (
    REASON_DUPLICATE_IN_B,
    REASON_MISSING_IN_B,
    REASON_ORPHAN_IN_B,
    REASON_VALUE_MISMATCH,
    disagreements_from_queryset,
)
from reconcile.importer import import_all
from reconcile.models import ImportAnomaly, Location, SystemARecord, SystemBEntry


# (reason, record_id) for every disagreement the submission claims to find.
EXPECTED_BY_ORG = {
    "ORG-A": {
        (REASON_MISSING_IN_B, "REC-1015"),
        (REASON_ORPHAN_IN_B, "REC-1999"),
        (REASON_DUPLICATE_IN_B, "REC-1042"),
        (REASON_DUPLICATE_IN_B, "REC-1055"),
        (REASON_VALUE_MISMATCH, "REC-1027"),
        (REASON_VALUE_MISMATCH, "REC-1064"),
        (REASON_VALUE_MISMATCH, "REC-1088"),
    },
    "ORG-B": {
        (REASON_MISSING_IN_B, "REC-1061"),
        (REASON_VALUE_MISMATCH, "REC-1003"),
        (REASON_VALUE_MISMATCH, "REC-1050"),
    },
}

# Rows whose System B reference is dirty but resolvable, and whose values agree.
# These are the deliberate non-errors; flagging any of them is a bug.
KNOWN_NON_ERRORS = ["REC-1034", "REC-1070", "REC-1112"]


class DatasetImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_all(settings.DATA_DIR)

    def test_every_source_row_is_imported(self):
        self.assertEqual(Location.objects.count(), 5)
        self.assertEqual(SystemARecord.objects.count(), 120)
        self.assertEqual(SystemBEntry.objects.count(), 121)

    def test_the_sample_dataset_needs_no_quarantine(self):
        """The bundled files have no key collisions, so nothing should be quarantined.

        This also guards against the quarantine logic becoming over-eager and
        rejecting rows that are merely dirty rather than unusable.
        """
        self.assertEqual(ImportAnomaly.objects.count(), 0)

    def test_known_dirty_values_are_recorded_not_dropped(self):
        blank_value = SystemBEntry.objects.get(entry_id="ENT/2026/4050")
        self.assertIsNone(blank_value.value)
        self.assertIn("value:BLANK_VALUE", blank_value.parse_issues)

        grouped = SystemBEntry.objects.get(entry_id="ENT/2026/4064")
        self.assertEqual(grouped.value, Decimal("125400.00"))
        self.assertEqual(grouped.value_raw, "1,25,400.00")

        blank_actor = SystemARecord.objects.get(record_id="REC-1050")
        self.assertEqual(blank_actor.actor_id, "")
        self.assertEqual(blank_actor.total_value, Decimal("160405.85"))


class GoldenDisagreementSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_all(settings.DATA_DIR)

    def all_disagreements(self, org_id=None):
        return disagreements_from_queryset(
            SystemARecord.objects.all(),
            SystemBEntry.objects.all(),
            Location.objects.all(),
            org_id=org_id,
        )

    def test_total_count_matches_the_claim(self):
        self.assertEqual(len(self.all_disagreements()), 10)

    def test_org_a_disagreements_match_exactly(self):
        found = {(d.reason, d.record_id) for d in self.all_disagreements("ORG-A")}
        self.assertEqual(found, EXPECTED_BY_ORG["ORG-A"])

    def test_org_b_disagreements_match_exactly(self):
        found = {(d.reason, d.record_id) for d in self.all_disagreements("ORG-B")}
        self.assertEqual(found, EXPECTED_BY_ORG["ORG-B"])

    def test_no_disagreement_leaks_between_tenants(self):
        org_a = {(d.reason, d.record_id) for d in self.all_disagreements("ORG-A")}
        org_b = {(d.reason, d.record_id) for d in self.all_disagreements("ORG-B")}

        self.assertEqual(org_a & org_b, set())
        # Every row belongs to exactly one tenant, so the parts must sum to the whole.
        self.assertEqual(len(org_a) + len(org_b), len(self.all_disagreements()))

    def test_every_result_is_stamped_with_the_requested_org(self):
        for org in ("ORG-A", "ORG-B"):
            self.assertEqual({d.org_id for d in self.all_disagreements(org)}, {org})

    def test_known_non_errors_are_never_flagged(self):
        flagged = {d.record_id for d in self.all_disagreements()}
        for record_id in KNOWN_NON_ERRORS:
            self.assertNotIn(record_id, flagged)

    def test_value_mismatches_report_both_sides(self):
        """Pins the compared fields: A total_value against B value.

        REC-1027's System B value is exactly System A's base_value, so comparing the
        wrong field would make this row look like agreement and vanish from the report.
        """
        mismatch = next(
            d for d in self.all_disagreements() if d.record_id == "REC-1027"
        )
        self.assertEqual(mismatch.reason, REASON_VALUE_MISMATCH)
        self.assertEqual(mismatch.a_value, Decimal("79259.03"))
        self.assertEqual(mismatch.b_value, Decimal("61921.12"))

    def test_grouped_number_mismatch_is_compared_numerically(self):
        mismatch = next(d for d in self.all_disagreements() if d.record_id == "REC-1064")
        self.assertEqual(mismatch.b_value, Decimal("125400.00"))
        self.assertEqual(mismatch.b_value_raw, "1,25,400.00")

    def test_duplicate_reports_both_entry_ids(self):
        duplicate = next(d for d in self.all_disagreements() if d.record_id == "REC-1055")
        self.assertEqual(duplicate.reason, REASON_DUPLICATE_IN_B)
        self.assertEqual(len(duplicate.b_entry_ids), 2)

    def test_orphan_points_at_a_record_absent_from_system_a(self):
        orphan = next(d for d in self.all_disagreements() if d.reason == REASON_ORPHAN_IN_B)
        self.assertEqual(orphan.record_id, "REC-1999")
        self.assertFalse(SystemARecord.objects.filter(record_id="REC-1999").exists())

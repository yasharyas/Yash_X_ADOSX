"""Tests for the disagreement decisions - the part the brief asks to cover.

One test per kind of disagreement we claim to catch, plus the non-errors that must
NOT be flagged. These use plain dataclasses so they exercise the decision logic
directly, with no database or HTTP in the way.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from reconcile.compare import (
    REASON_DUPLICATE_IN_B,
    REASON_MISSING_IN_B,
    REASON_ORPHAN_IN_B,
    REASON_VALUE_MISMATCH,
    ARecord,
    BEntry,
    find_disagreements,
)
from reconcile.parsing import normalize_record_ref


LOC_ORG = {"LOC-101": "ORG-A", "LOC-201": "ORG-B"}


def b_entry(entry_id, ref, location_id="LOC-101", value=None, value_raw=""):
    """Build a BEntry with the ref normalized the same way the importer does.

    Why route through normalize_record_ref instead of hardcoding the normalized id:
    it keeps the fixtures honest, so a test can't pass with a normalization the
    real import would never produce.
    """
    return BEntry(
        entry_id=entry_id,
        record_ref_raw=ref,
        record_id_normalized=normalize_record_ref(ref),
        location_id=location_id,
        value=value,
        value_raw=value_raw,
    )


class MissingInBTests(SimpleTestCase):
    def test_a_record_with_no_b_entry_is_flagged(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("10.00"), "10.00")]

        found = find_disagreements(a, [], LOC_ORG)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, REASON_MISSING_IN_B)
        self.assertEqual(found[0].record_id, "REC-1")
        self.assertEqual(found[0].a_value, Decimal("10.00"))
        self.assertIsNone(found[0].b_value)
        self.assertEqual(found[0].org_id, "ORG-A")


class OrphanInBTests(SimpleTestCase):
    def test_b_entry_pointing_at_missing_record_is_flagged(self):
        entries = [b_entry("ENT-1", "REC-9999", value=Decimal("5"), value_raw="5")]

        found = find_disagreements([], entries, LOC_ORG)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, REASON_ORPHAN_IN_B)
        self.assertEqual(found[0].b_entry_ids, ("ENT-1",))
        self.assertIsNone(found[0].a_value)

    def test_unnormalizable_ref_is_also_an_orphan(self):
        """A ref we cannot interpret still has to be reported, never dropped."""
        entries = [b_entry("ENT-2", "garbage", value=Decimal("5"), value_raw="5")]

        found = find_disagreements([], entries, LOC_ORG)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, REASON_ORPHAN_IN_B)
        self.assertIsNone(found[0].record_id)


class DuplicateInBTests(SimpleTestCase):
    def test_same_record_entered_twice_is_flagged(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("10"), "10")]
        entries = [
            b_entry("ENT-1", "REC-1", value=Decimal("10"), value_raw="10"),
            b_entry("ENT-2", "REC-1", value=Decimal("10"), value_raw="10"),
        ]

        found = find_disagreements(a, entries, LOC_ORG)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, REASON_DUPLICATE_IN_B)
        self.assertEqual(set(found[0].b_entry_ids), {"ENT-1", "ENT-2"})

    def test_duplicate_is_flagged_even_when_both_values_match_a(self):
        """Guards a deliberate decision: the duplication itself is the problem.

        REC-1042 in the real data has two identical entries. If someone "optimized"
        this to only flag differing values, that row would vanish from the report.
        """
        a = [ARecord("REC-1", "LOC-101", Decimal("10"), "10")]
        entries = [
            b_entry("ENT-1", "REC-1", value=Decimal("10"), value_raw="10"),
            b_entry("ENT-2", "REC-1", value=Decimal("10"), value_raw="10"),
        ]

        found = find_disagreements(a, entries, LOC_ORG)

        self.assertEqual([d.reason for d in found], [REASON_DUPLICATE_IN_B])

    def test_duplicate_reports_both_differing_values(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("179877.32"), "179877.32")]
        entries = [
            b_entry("ENT-1", "REC-1", value=Decimal("71950.93"), value_raw="71950.93"),
            b_entry("ENT-2", "REC-1", value=Decimal("107926.39"), value_raw="107926.39"),
        ]

        found = find_disagreements(a, entries, LOC_ORG)

        self.assertEqual(found[0].reason, REASON_DUPLICATE_IN_B)
        self.assertIn("71950.93", found[0].b_value_raw)
        self.assertIn("107926.39", found[0].b_value_raw)


class ValueMismatchTests(SimpleTestCase):
    def test_different_values_are_flagged(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("100.00"), "100.00")]
        entries = [b_entry("ENT-1", "REC-1", value=Decimal("80.00"), value_raw="80.00")]

        found = find_disagreements(a, entries, LOC_ORG)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, REASON_VALUE_MISMATCH)
        self.assertEqual(found[0].a_value, Decimal("100.00"))
        self.assertEqual(found[0].b_value, Decimal("80.00"))

    def test_blank_b_value_against_a_number_is_a_mismatch(self):
        """REC-1050's blank B value is a disagreement, not "no opinion"."""
        a = [ARecord("REC-1", "LOC-101", Decimal("160405.85"), "160405.85")]
        entries = [b_entry("ENT-1", "REC-1", value=None, value_raw="")]

        found = find_disagreements(a, entries, LOC_ORG)

        self.assertEqual([d.reason for d in found], [REASON_VALUE_MISMATCH])
        self.assertIsNone(found[0].b_value)

    def test_equal_values_written_differently_are_not_a_mismatch(self):
        """Trailing zeros differ as text but are equal as Decimals."""
        a = [ARecord("REC-1", "LOC-101", Decimal("50.00"), "50.00")]
        entries = [b_entry("ENT-1", "REC-1", value=Decimal("50.000"), value_raw="50.000")]

        self.assertEqual(find_disagreements(a, entries, LOC_ORG), [])


class NonErrorTests(SimpleTestCase):
    """The brief grades whether "the non-error is correctly identified as a non-error"."""

    def test_dirty_refs_that_resolve_and_agree_are_not_flagged(self):
        a = [
            ARecord("REC-1034", "LOC-101", Decimal("10.00"), "10.00"),
            ARecord("REC-1070", "LOC-201", Decimal("50.00"), "50.00"),
            ARecord("REC-1112", "LOC-101", Decimal("70.00"), "70.00"),
        ]
        entries = [
            b_entry("ENT-34", "rec1034", "LOC-101", Decimal("10.00"), "10.00"),
            b_entry("ENT-70", " REC - 1070 ", "LOC-201", Decimal("50.00"), "50.00"),
            b_entry("ENT-112", "1112", "LOC-101", Decimal("70.00"), "70.00"),
        ]

        self.assertEqual(find_disagreements(a, entries, LOC_ORG), [])

    def test_clean_matching_record_is_not_flagged(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("10.00"), "10.00")]
        entries = [b_entry("ENT-1", "REC-1", value=Decimal("10.00"), value_raw="10.00")]

        self.assertEqual(find_disagreements(a, entries, LOC_ORG), [])


class TenantScopeTests(SimpleTestCase):
    def test_org_filter_hides_other_tenants_rows(self):
        a = [
            ARecord("REC-1", "LOC-101", Decimal("10"), "10"),
            ARecord("REC-2", "LOC-201", Decimal("20"), "20"),
        ]

        found = find_disagreements(a, [], LOC_ORG, org_id="ORG-A")

        self.assertEqual([d.record_id for d in found], ["REC-1"])
        self.assertEqual({d.org_id for d in found}, {"ORG-A"})

    def test_orphan_is_scoped_by_its_own_location(self):
        """An orphan has no A record, so its org must come from the B row's location."""
        entries = [b_entry("ENT-1", "REC-9999", "LOC-201", Decimal("5"), "5")]

        self.assertEqual(find_disagreements([], entries, LOC_ORG, org_id="ORG-A"), [])
        self.assertEqual(len(find_disagreements([], entries, LOC_ORG, org_id="ORG-B")), 1)

    def test_unfiltered_result_is_the_union_of_both_tenants(self):
        a = [
            ARecord("REC-1", "LOC-101", Decimal("10"), "10"),
            ARecord("REC-2", "LOC-201", Decimal("20"), "20"),
        ]

        total = len(find_disagreements(a, [], LOC_ORG))
        per_org = sum(
            len(find_disagreements(a, [], LOC_ORG, org_id=org)) for org in ("ORG-A", "ORG-B")
        )

        self.assertEqual(total, per_org)

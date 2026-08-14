"""Tests for disagreement comparison logic."""

from decimal import Decimal

from django.test import SimpleTestCase

from reconcile.compare import (
    ARecord,
    BEntry,
    REASON_DUPLICATE_IN_B,
    REASON_MISSING_IN_B,
    REASON_ORPHAN_IN_B,
    REASON_VALUE_MISMATCH,
    find_disagreements,
)
from reconcile.parsing import normalize_record_ref, parse_decimal


LOC_ORG = {"LOC-101": "ORG-A", "LOC-201": "ORG-B"}


class ParseHelpersTests(SimpleTestCase):
    def test_normalize_dirty_refs(self):
        self.assertEqual(normalize_record_ref("rec1034"), "REC-1034")
        self.assertEqual(normalize_record_ref(" REC - 1070 "), "REC-1070")
        self.assertEqual(normalize_record_ref("1112"), "REC-1112")
        self.assertEqual(normalize_record_ref("REC-1001"), "REC-1001")

    def test_parse_indian_comma_number(self):
        value, issues = parse_decimal("1,25,400.00")
        self.assertEqual(value, Decimal("125400.00"))
        self.assertEqual(issues, [])

    def test_parse_blank(self):
        value, issues = parse_decimal("")
        self.assertIsNone(value)
        self.assertEqual(issues, ["BLANK_VALUE"])


class CompareTests(SimpleTestCase):
    def test_missing_in_b(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("10.00"), "10.00")]
        disagreements = find_disagreements(a, [], LOC_ORG)
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].reason, REASON_MISSING_IN_B)
        self.assertEqual(disagreements[0].record_id, "REC-1")
        self.assertEqual(disagreements[0].org_id, "ORG-A")

    def test_orphan_in_b(self):
        b = [
            BEntry(
                entry_id="ENT-1",
                record_ref_raw="REC-9999",
                record_id_normalized="REC-9999",
                location_id="LOC-101",
                value=Decimal("5"),
                value_raw="5",
            )
        ]
        disagreements = find_disagreements([], b, LOC_ORG)
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].reason, REASON_ORPHAN_IN_B)
        self.assertEqual(disagreements[0].b_entry_ids, ("ENT-1",))

    def test_duplicate_in_b(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("10"), "10")]
        b = [
            BEntry("ENT-1", "REC-1", "REC-1", "LOC-101", Decimal("10"), "10"),
            BEntry("ENT-2", "REC-1", "REC-1", "LOC-101", Decimal("10"), "10"),
        ]
        disagreements = find_disagreements(a, b, LOC_ORG)
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].reason, REASON_DUPLICATE_IN_B)
        self.assertEqual(set(disagreements[0].b_entry_ids), {"ENT-1", "ENT-2"})

    def test_value_mismatch(self):
        a = [ARecord("REC-1", "LOC-101", Decimal("100.00"), "100.00")]
        b = [BEntry("ENT-1", "REC-1", "REC-1", "LOC-101", Decimal("80.00"), "80.00")]
        disagreements = find_disagreements(a, b, LOC_ORG)
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].reason, REASON_VALUE_MISMATCH)
        self.assertEqual(disagreements[0].a_value, Decimal("100.00"))
        self.assertEqual(disagreements[0].b_value, Decimal("80.00"))

    def test_dirty_ref_matching_equal_values_is_not_a_disagreement(self):
        """Non-error: messy record_ref that normalizes and agrees must not be flagged."""
        a = [ARecord("REC-1070", "LOC-201", Decimal("50.00"), "50.00")]
        b = [
            BEntry(
                entry_id="ENT-70",
                record_ref_raw=" REC - 1070 ",
                record_id_normalized=normalize_record_ref(" REC - 1070 "),
                location_id="LOC-201",
                value=Decimal("50.00"),
                value_raw="50.00",
            )
        ]
        disagreements = find_disagreements(a, b, LOC_ORG)
        self.assertEqual(disagreements, [])

    def test_org_filter_hides_other_tenant(self):
        a = [
            ARecord("REC-1", "LOC-101", Decimal("10"), "10"),
            ARecord("REC-2", "LOC-201", Decimal("20"), "20"),
        ]
        disagreements = find_disagreements(a, [], LOC_ORG, org_id="ORG-A")
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].record_id, "REC-1")
        self.assertEqual(disagreements[0].org_id, "ORG-A")

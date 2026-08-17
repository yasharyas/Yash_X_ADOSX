"""Tests for the cleaning rules applied to dirty cells and references."""

from decimal import Decimal

from django.test import SimpleTestCase

from reconcile.parsing import normalize_record_ref, parse_date, parse_decimal


class NormalizeRecordRefTests(SimpleTestCase):
    """Each case here is a real spelling found in system_b.csv.

    These matter because a normalization regression silently converts a matching
    record into a false "missing"/"orphan" disagreement.
    """

    def test_already_canonical(self):
        self.assertEqual(normalize_record_ref("REC-1001"), "REC-1001")

    def test_lowercase_without_hyphen(self):
        self.assertEqual(normalize_record_ref("rec1034"), "REC-1034")

    def test_padded_with_spaces_around_hyphen(self):
        self.assertEqual(normalize_record_ref(" REC - 1070 "), "REC-1070")

    def test_bare_number_gets_prefix(self):
        self.assertEqual(normalize_record_ref("1112"), "REC-1112")

    def test_unusable_refs_return_none(self):
        """None signals "genuine orphan" rather than raising and killing the import."""
        for value in (None, "", "   ", "not-a-ref"):
            self.assertIsNone(normalize_record_ref(value), msg=repr(value))


class ParseDecimalTests(SimpleTestCase):
    def test_plain_number(self):
        value, issues = parse_decimal("88969.92")
        self.assertEqual(value, Decimal("88969.92"))
        self.assertEqual(issues, [])

    def test_indian_grouped_number(self):
        """system_b.csv contains 1,25,400.00; commas must not defeat parsing."""
        value, issues = parse_decimal("1,25,400.00")
        self.assertEqual(value, Decimal("125400.00"))
        self.assertEqual(issues, [])

    def test_blank_is_reported_distinctly_from_garbage(self):
        self.assertEqual(parse_decimal(""), (None, ["BLANK_VALUE"]))
        self.assertEqual(parse_decimal("abc"), (None, ["UNPARSEABLE_NUMBER"]))

    def test_returns_decimal_not_float(self):
        """Guards the money-precision decision; float would risk false mismatches."""
        value, _ = parse_decimal("0.1")
        self.assertIsInstance(value, Decimal)


class ParseDateTests(SimpleTestCase):
    def test_iso_format(self):
        value, issues = parse_date("2026-03-20")
        self.assertEqual(value.isoformat(), "2026-03-20")
        self.assertEqual(issues, [])

    def test_blank_and_garbage_are_reported(self):
        self.assertEqual(parse_date(""), (None, ["BLANK_DATE"]))
        self.assertEqual(parse_date("nope"), (None, ["UNPARSEABLE_DATE"]))

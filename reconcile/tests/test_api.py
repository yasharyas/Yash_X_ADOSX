"""Tests for the API contract, focused on tenant isolation.

The comparison logic is tested directly elsewhere; these tests cover the things
only the HTTP layer can get wrong - chiefly that a caller cannot obtain another
tenant's rows, which is the one rule the brief says must never be broken.
"""

from decimal import Decimal

from django.conf import settings
from django.test import TestCase

from reconcile.importer import import_all


class OrgListApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_all(settings.DATA_DIR)

    def test_lists_orgs_derived_from_locations(self):
        response = self.client.get("/api/orgs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([o["org_id"] for o in response.json()], ["ORG-A", "ORG-B"])


class DisagreementApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_all(settings.DATA_DIR)

    def get(self, **params):
        return self.client.get("/api/disagreements/", params)

    def test_org_id_is_required(self):
        """Refusing the request is the safe default; a silent "all rows" would leak."""
        response = self.get()

        self.assertEqual(response.status_code, 400)
        self.assertIn("org_id", response.json()["detail"])

    def test_returns_only_the_requested_tenants_rows(self):
        payload = self.get(org_id="ORG-A").json()

        self.assertEqual(payload["count"], 7)
        self.assertEqual({row["org_id"] for row in payload["results"]}, {"ORG-A"})

    def test_other_tenants_records_are_absent(self):
        org_a_records = {row["record_id"] for row in self.get(org_id="ORG-A").json()["results"]}
        org_b_records = {row["record_id"] for row in self.get(org_id="ORG-B").json()["results"]}

        self.assertEqual(org_a_records & org_b_records, set())
        # A record known to belong to ORG-B must not appear under ORG-A.
        self.assertIn("REC-1003", org_b_records)
        self.assertNotIn("REC-1003", org_a_records)

    def test_unknown_org_returns_nothing_rather_than_everything(self):
        payload = self.get(org_id="ORG-DOES-NOT-EXIST").json()

        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])

    def test_filter_by_reason(self):
        payload = self.get(org_id="ORG-A", reason="value_mismatch").json()

        self.assertEqual(payload["count"], 3)
        self.assertEqual({row["reason"] for row in payload["results"]}, {"value_mismatch"})

    def test_unknown_reason_is_rejected(self):
        """Rejecting beats silently ignoring, which would show unfiltered rows."""
        response = self.get(org_id="ORG-A", reason="not-a-reason")

        self.assertEqual(response.status_code, 400)

    def test_sort_by_value_ascending_and_descending(self):
        def values(ordering):
            rows = self.get(org_id="ORG-A", ordering=ordering).json()["results"]
            # Rows without either value sort last and are excluded from the ordering check.
            return [
                Decimal(row["a_value"] or row["b_value"])
                for row in rows
                if row["a_value"] or row["b_value"]
            ]

        ascending = values("value")
        descending = values("-value")

        self.assertEqual(ascending, sorted(ascending))
        self.assertEqual(descending, sorted(descending, reverse=True))

    def test_unknown_ordering_is_rejected(self):
        self.assertEqual(self.get(org_id="ORG-A", ordering="drop table").status_code, 400)

    def test_row_shape_includes_both_systems_values_and_location(self):
        row = next(
            r
            for r in self.get(org_id="ORG-B").json()["results"]
            if r["record_id"] == "REC-1003"
        )

        # The brief asks for the reason, both systems' versions, and the location.
        self.assertEqual(row["reason"], "value_mismatch")
        self.assertEqual(row["a_value"], "121388.0100")
        self.assertEqual(row["b_value"], "94834.3800")
        self.assertEqual(row["location_id"], "LOC-202")
        self.assertTrue(row["detail"])

    def test_values_are_serialized_as_strings_to_preserve_precision(self):
        row = self.get(org_id="ORG-B").json()["results"][0]

        for key in ("a_value", "b_value"):
            if row[key] is not None:
                self.assertIsInstance(row[key], str)

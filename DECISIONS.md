# Decisions

Each entry: the decision, the alternative rejected, and the reasoning that separated
them. `CHOICES.md` has the longer version with more alternatives per decision.

1. **Compare System A `total_value` to System B `value`.**
   Rejected: comparing `base_value`.
   Reasoning: most matching rows agree on `total_value`, and three of the planted
   mismatches are exactly A's `base_value` copied into B; comparing `base_value` would
   hide the very bugs we are asked to find.

2. **Normalize messy `record_ref` values before matching.**
   Rejected: exact string equality on `record_ref`.
   Reasoning: `rec1034`, `' REC - 1070 '` and bare `1112` all point at real records, so
   matching raw strings would manufacture false disagreements out of clean data.

3. **Store raw CSV text alongside nullable parsed fields plus a `parse_issues` list.**
   Rejected: storing only the parsed value, or rejecting rows that fail to parse.
   Reasoning: an unparseable number must cost neither the row nor the original text; the
   issue list turns a silent drop into an auditable record of what was dirty and where.

4. **Quarantine rows with a blank or duplicate natural key into `ImportAnomaly`, and
   assert `rows_read == rows_stored + quarantined` per file.**
   Rejected: `update_or_create` on the source identifier, reporting rows read.
   Reasoning: keying on the source identifier let a duplicate key silently overwrite an
   imported row while still being counted as imported; the quarantine keeps the row and
   the reconciliation makes the loss impossible to miss.

5. **Always flag duplicates, even when the two B values match each other and A.**
   Rejected: only flagging duplicates when the values also differ.
   Reasoning: "the same record entered into System B twice" is its own disagreement class
   in the brief; the duplication is the defect, independent of value.

6. **Treat a blank or unparseable B value as a value mismatch when A has a number.**
   Rejected: skipping the comparison as "no data to compare".
   Reasoning: the two systems still do not agree on the amount, and treating blank as
   silence would hide a real discrepancy (`REC-1050`).

7. **Pin the expected disagreement set for the real CSVs in a golden-set test.**
   Rejected: relying only on unit tests built from hand-made fixtures.
   Reasoning: fixtures verify the rules but not which fields are fed into them; swapping
   `total_value` for `base_value` yields 118 disagreements with every fixture test green.

8. **Enforce tenant scope server-side via a required `org_id` query parameter.**
   Rejected: returning the global list and filtering in the React UI.
   Reasoning: filtering client-side still sends every tenant's rows over the wire, which
   is precisely the boundary the brief says must not be crossed.

9. **Keep the comparison a pure function over plain frozen dataclasses.**
   Rejected: expressing the rules inside DRF views, querysets, or SQL.
   Reasoning: the same code path serves the API and the tests, so a passing test proves
   the behavior that ships, with no HTTP or database fixtures needed.

10. **Stack: Django REST + Vite React SPA on SQLite.**
    Rejected: Next.js frontend; PostgreSQL.
    Reasoning: a clear API/UI split suits a one-day feature, and SQLite keeps a clean
    clone runnable with zero external setup for a 120-row dataset.

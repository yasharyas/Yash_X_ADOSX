# Technical choices guide

This document explains, for each significant decision, **what was used**, **what
alternatives existed**, and **why the alternatives were rejected**. It complements
`DECISIONS.md` (which is a short log) with the full reasoning and covers the code
structure, not just the product-level calls.

---

## 1. Stack: Django REST + Vite React SPA

**Used:** A Django + Django REST Framework backend exposing a JSON API, with a
separate Vite React single-page app for the table.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Django templates + HTMX (server-rendered table) | Fewer moving parts, but the brief explicitly lists "Django and React or Next.js preferred". A clean API/UI split also demonstrates back-to-front thinking better. |
| Next.js frontend | Perfectly valid, but it pulls in SSR/routing machinery this one screen never needs. A Vite SPA is lighter and starts faster. |
| Flask / FastAPI | Would work, but Django's ORM, migrations, admin, and management commands remove a lot of boilerplate for a data-import task. |

---

## 2. Database: SQLite

**Used:** SQLite (Django's default).

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| PostgreSQL | More "production realistic" and has richer types, but it needs a running server, which hurts the "runs from a clean clone" criterion. 120 rows do not need it. |
| In-memory / no DB (parse CSVs on each request) | Simplest to start, but the brief says "Import both CSVs into a database... Design the tables yourself", so a real schema is part of what is being graded. |

---

## 3. Schema: store raw text **and** parsed values, plus `parse_issues`

**Used:** Every model keeps the original CSV string (`*_raw`) alongside a nullable
parsed field (`Decimal`/`Date`), and a `parse_issues` JSON list.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Store only the parsed value | A row with an un-parseable number would either be dropped or lose its original data. The brief forbids silent drops and rewards surfacing the mess. |
| Store only the raw text | Then every comparison would re-parse on the fly, duplicating logic and making sorting by value awkward. |
| Reject/skip rows that fail to parse | Directly violates "must survive all of it without silently dropping rows". |

---

## 4. `record_ref` normalization at import time

**Used:** `normalize_record_ref` collapses `REC-1034`, `rec1034`, `' REC - 1070 '`,
and bare `1112` to a canonical `REC-<digits>`, stored in `record_id_normalized`.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Exact string match on `record_ref` | Would flag every clean-but-ugly reference as a false orphan/missing. These are the deliberate "non-errors" the brief wants correctly identified. |
| Normalize inside the comparison, on every run | Wastes work and hides the rule in the hot path. Normalizing once on import means matching is plain equality and the value can be DB-indexed. |
| Fuzzy matching (edit distance) | Overkill and dangerous: it could match genuinely different ids. The dirt here is formatting, not typos, so deterministic rules are safer. |

---

## 5. Money as `Decimal`, compared exactly

**Used:** `parse_decimal` returns `Decimal`; comparison uses `==` on `Decimal`.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| `float` | IEEE rounding (`0.1 + 0.2 != 0.3`) could turn equal values into false "value mismatch" rows. Money should never be a float. |
| Compare the raw strings | `"88969.92"` vs `"88969.920"` are equal numbers but unequal strings; and it would not handle the `1,25,400.00` case. |
| Integer cents | Works, but requires knowing the scale of every field up front; `Decimal` handles arbitrary precision without that assumption. |

---

## 6. Which field defines "value mismatch": A `total_value` vs B `value`

**Used:** Compare System A's `total_value` to System B's `value`.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Compare `base_value` | Several planted mismatches are exactly A's `base_value` copied into B's `value`; comparing `base_value` would *hide* those bugs instead of catching them. |
| Compare every column (date, location, category) | The brief's minimum is presence/value disagreements. Flagging date-only (`REC-1009`) or location-only (`REC-1077`) drift would add noise beyond the stated scope; noted as an explicit non-goal. |

---

## 7. Comparison as one pure function

**Used:** `find_disagreements` operates on plain frozen dataclasses with no DB or
HTTP; `disagreements_from_queryset` adapts Django models into it.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Put the logic in the DRF view / queryset | Tests would then need HTTP or DB fixtures, and the rules would be tangled with serialization. |
| Do it in raw SQL | Fast, but the dirty normalization and null rules are far clearer in Python, and SQL would be much harder to unit test row-by-row. |
| ORM annotations/`Case`/`When` | Possible, but the four-way branching (missing/orphan/duplicate/mismatch) is more readable as procedural code, and keeps the algorithm DB-agnostic. |

---

## 8. Tenant isolation via a required `org_id` query param

**Used:** `GET /api/disagreements/` returns `400` unless `org_id` is supplied, then
filters results to that org's locations server-side.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Return everything, filter in the React UI | The raw data would still cross the wire, which is exactly the "leak across the boundary" the brief warns against. Isolation must be server-side. |
| Real authentication with per-user org | The brief says "Authentication. Skip it entirely." A required param models the boundary without the auth machinery. |
| Default to some org when omitted | A silent default is how cross-tenant leaks happen; forcing the caller to be explicit is safer. |

---

## 8b. Unusable natural keys: quarantine rather than overwrite

**Used:** The three main tables key on the CSV's own identifier. A row whose key is blank
or already seen in the same file is written to `ImportAnomaly` (file, line number, reason,
full raw row) instead of being stored, and each file reports
`rows_read == rows_stored + quarantined`.

**Why this was needed:** with plain `update_or_create` on a natural key, a worse export
containing a duplicate `entry_id` silently overwrote the earlier row, while the importer
reported the row as imported; it printed `system_a=4, system_b=2` when the database held
only 2 and 1 rows.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Surrogate integer PKs, natural key as a non-unique column | Every row would persist with no quarantine table, which is arguably cleaner. Rejected for scope: it changes the identity model the comparison and orphan de-duplication rely on, for a collision the real dataset does not contain. This is the direction I would take it with more time. |
| Let the last row win (current `update_or_create` behavior) | Silently destroys data and makes the reported count a lie; the exact failure the brief grades. |
| Abort the whole import on the first duplicate | Safe but useless against a "real exports are worse" file: one bad row would block 120 good ones. |
| Skip the row with a log line | Better than overwriting, but a log is not queryable and the row is still gone. Quarantining keeps it in the database. |

---

## 9. Import strategy: atomic wipe-and-reload

**Used:** `import_all` is wrapped in `@transaction.atomic` and deletes all rows
before reloading.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Incremental upsert / diff merge | More realistic for huge daily exports, but at 120 rows it adds complexity and risks stale rows skewing results. A clean reload is fully deterministic. |
| Non-atomic import | A malformed file partway through could leave the DB half-updated (new locations, old entries). Atomicity guarantees all-or-nothing. |

---

## 10. Duplicates are always flagged, even when values match

**Used:** Two B entries for the same record → `duplicate_in_b`, regardless of
whether the two values are equal (`REC-1042` equal, `REC-1055` different).

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Only flag duplicates when values differ | "The same record entered into System B twice" is its own disagreement class in the brief; the duplication itself is the problem, independent of value. |

---

## 11. Blank/unparseable B value treated as a mismatch

**Used:** When A has a number and B's `value` is blank or garbage, it is reported
as `value_mismatch` (`REC-1050` blank; `REC-1064` `1,25,400.00`).

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Skip comparison when B has no parseable number | The two systems still do not agree on the amount, which is the thing anyone cares about. Treating blank as "no opinion" would hide a real discrepancy. |

---

## 12. Frontend state: local `useState`, server-side sorting

**Used:** Plain React hooks; the header click changes an `ordering` param and the
server sorts.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Redux / Zustand / Context | One screen with a few controls does not justify a state library. |
| Sort/filter entirely client-side | Fine at this size, but keeping sort logic on the server means one canonical ordering and less duplicated logic; the client stays "dumb". |
| A table component library (AG Grid, MUI) | The brief says a plain table is the correct answer and not to spend the day on CSS. |

---

## 13. Testing: layered, with a golden set as the regression net

**Used:** Four layers, split by concern in `reconcile/tests/`:

| File | Protects |
| --- | --- |
| `test_compare.py` | The disagreement decisions, one test per kind, plus the non-errors. Uses dataclass fixtures, no DB. |
| `test_parsing.py` | The cleaning rules for dirty cells and refs. |
| `test_importer.py` | That dirty rows survive and nothing is silently dropped, using deliberately worse CSVs written to a temp directory. |
| `test_dataset.py` | A golden set: the exact expected disagreements per org for the real CSVs. |
| `test_api.py` | Tenant isolation and the filter/sort contract. |

**Why the golden set was necessary:** fixture-based unit tests validate the rules but not
which fields are passed into them. Changing the adapter to read `base_value` instead of
`total_value` made the app report 118 disagreements instead of 10 with all fixture tests
still passing. The golden set fails immediately on that change.

**Verified by mutation testing:** seven regressions were injected one at a time, wrong
compared field, tenant filter removed, orphan detection removed, duplicates flagged only
when values differ, blank treated as agreement, bare-digit ref normalization dropped, and
the importer silently overwriting duplicate keys. All seven were caught.

**Alternatives considered**

| Alternative | Why not chosen |
| --- | --- |
| Only unit tests on the comparison | This is what the brief minimally asks for, but as shown above it leaves the single most important decision unprotected. |
| Only end-to-end tests through the API | Slower, and a failure points at "the page is wrong" rather than at the rule that broke. |
| Snapshot/approval testing of the whole API response | Would catch the same regressions, but a diff of 10 JSON objects is far less readable than a named assertion about `REC-1027`. |
| `pytest` instead of Django's test runner | Nicer fixtures and parametrization, but it is another dependency and `manage.py test` works from a clean clone with nothing extra installed. |

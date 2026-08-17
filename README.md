# ADOSX disagreement reconciler

Find records where System A and System B disagree, without leaking rows across tenant (org) boundaries.

## How to run

### Prerequisites

- Python 3.11+
- Node.js 18+

### Backend

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py import_csv
python manage.py runserver
```

API listens on http://127.0.0.1:8000

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: http://127.0.0.1:5173 (proxies `/api` to Django)

### Tests

```bash
python manage.py test reconcile
```

61 tests, all passing.

## What it finds

On the bundled dataset: **10 disagreements** (7 for `ORG-A`, 3 for `ORG-B`), with no
overlap between tenants.

| Reason | Records |
| --- | --- |
| Missing in B | `REC-1015`, `REC-1061` |
| Orphan in B | `REC-1999` |
| Duplicate in B | `REC-1042` (identical values), `REC-1055` (differing values) |
| Value mismatch | `REC-1003`, `REC-1027`, `REC-1088` (B holds A's `base_value`), `REC-1050` (B blank), `REC-1064` (`1,25,400.00`) |

Correctly **not** flagged: `REC-1034`, `REC-1070`, `REC-1112`. Their System B refs are
dirty (`rec1034`, `' REC - 1070 '`, `1112`) but they resolve to real records whose
values agree, so they are non-errors.

## What I built

- Django models for locations, System A records, and System B entries that keep
  **raw CSV strings** alongside nullable parsed fields and a `parse_issues` list
- An importer (`python manage.py import_csv`) that loads all three CSVs and
  **never silently drops a row**. Two distinct kinds of mess are handled differently:
  - a bad **value** (blank, `abc`, `1,25,400.00`) still becomes a normal row, with the
    raw text kept and the problem recorded in `parse_issues`
  - a bad **key** (blank or duplicate `record_id`/`entry_id`) cannot share a primary
    key, so the row is stored verbatim in `ImportAnomaly` (a quarantine table) with its
    file and line number, and reported loudly
  - the importer asserts `rows_read == rows_stored + quarantined` per file, so
    "nothing was dropped" is a checked invariant rather than a claim
- Comparison logic that flags: missing in B, orphan in B, duplicate in B, and
  value mismatch (A `total_value` vs B `value`)
- Tenant scoping via a required `org_id` on the disagreements API, filtered server-side
- A plain React table: filter by reason, sort by value, switch org
- Tests split by concern (`reconcile/tests/`): the comparison rules, the parsing rules,
  the importer's no-drop guarantee, a **golden-set** check against the real CSVs, and
  API tenant isolation

### On the tests

The comparison tests are the ones the brief asks for: one per disagreement kind, plus
the dirty-ref non-errors. The golden-set test in `test_dataset.py` exists because unit
tests with hand-built fixtures cannot catch a mistake in *which data is fed into* the
rules: pointing the comparison at `base_value` instead of `total_value` makes the app
report 118 disagreements while every fixture-based test still passes.

I sanity-checked the suite by injecting seven regressions one at a time (wrong compared
field, tenant filter removed, orphan detection removed, duplicates only flagged when
values differ, blank treated as agreement, bare-digit ref normalization dropped,
importer silently overwriting duplicate keys). All seven were caught.

## What I deliberately did not build

- Authentication / real login (org is selected in the UI)
- Polished CSS
- Flagging date-only or location-only drift as disagreements. `REC-1009` differs only on
  date and `REC-1077` only on location; both are reported as agreeing, because the brief
  scopes disagreement to presence and value
- Pagination, caching, or production deployment
- A UI surface for quarantined rows and parse issues (currently visible via the
  import output and Django admin only)
- Resolving / writing back corrections

## How I worked with the agent

I used Cursor to scaffold Django + Vite and to draft the models, importer, comparison,
API, and UI. Before writing any code I read the three CSVs myself and worked out what the
answer should be (row counts, which refs were dirty, which values disagreed) so I had an
independent expectation to check the agent's output against. That mattered more than any
individual prompt: most of the agent's mistakes were plausible-looking code that produced
the wrong count, and the only reason I caught them was that I already knew the count.

Where I pushed back hardest was on anything that could hide data. I also mutation-tested
my own suite (deliberately breaking the logic to confirm a test failed), because a passing
suite that catches nothing is worse than no suite.

### a. Name one thing the AI agent got wrong. How did you notice?

The importer looked correct and was quietly losing rows. Each loader used
`update_or_create` keyed on the CSV's own identifier and returned a count of *rows read*,
which it reported as rows imported. On the bundled data those numbers happen to agree, so
nothing looked wrong. I only caught it by writing a deliberately worse export with two rows
sharing a `record_id`, two sharing an `entry_id`, two with blank ids, because the brief
says to assume real exports are worse. The importer printed `system_a=4, system_b=2`, while
the database actually held 2 and 1 rows: three rows overwritten, and the success message
claiming otherwise. That is now fixed with the quarantine table plus a
`rows_read == rows_stored + quarantined` assertion, and a test that reproduces it.

The agent also got the reference matching wrong earlier, joining on the raw `record_ref`
string, which turned `rec1034`, `' REC - 1070 '` and `1112` into false disagreements. I
noticed by counting "missing" rows before and after normalization: it found 4 missing and
3 orphans where the real answer was 2 and 1.

### b. Which part of your submission are you least confident about, and why?

`REC-1077`, where the two systems disagree about *which tenant the row belongs to*:
System A says `LOC-102` (`ORG-A`) and System B says `LOC-201` (`ORG-B`). Their values
agree, so I do not flag it, and I scope each disagreement by the location of the system it
originates from (A's location for A-centric reasons, B's for orphans). But I am not
certain that is the right call for a product whose core promise is tenant isolation: an
argument exists that a cross-org location mismatch is the *most* serious disagreement in
the file, since it means one of the two systems is attributing a row to the wrong
customer. I chose to stay inside the brief's definition rather than invent a fifth reason,
but it is the decision I would most want to talk through.

### c. If you had a second day, what would you fix first?

Surface the mess in the UI. Right now the importer's guarantee is real but invisible from
the screen: quarantined rows and `parse_issues` are only reachable through the import
output or Django admin, so someone using the app cannot see that `REC-1050`'s value was
blank rather than zero, or that a row was quarantined at all. I would add a data-quality
panel showing quarantined rows with their file and line number, and mark any disagreement
whose value failed to parse, so the screen tells the same story the importer does.

## API sketch

- `GET /api/orgs/`
- `GET /api/disagreements/?org_id=ORG-A&reason=value_mismatch&ordering=value`

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

## What I built

- Django models for locations, System A records, and System B entries that keep **raw CSV strings** plus nullable parsed fields and `parse_issues`
- An importer (`python manage.py import_csv`) that loads all three CSVs and **never silently drops a row**
- Comparison logic that flags:
  - missing in B
  - orphan in B
  - duplicate in B
  - value mismatch (`total_value` vs B `value`)
- Tenant scoping via required `org_id` on the disagreements API
- A plain React table: filter by reason, sort by value, switch org
- Unit tests for each disagreement kind plus a dirty-ref **non-error**

## What I deliberately did not build

- Authentication / real login (org is selected in the UI)
- Polished CSS
- Flagging date-only or location-only drift as disagreements
- Pagination, caching, or production deployment
- Resolving / writing back corrections

## How I worked with the agent

I used Cursor to scaffold Django + Vite, draft models/importer/compare/API/UI, and iterate on tests. I inspected the CSVs myself first (row counts, dirty `record_ref`s, value mismatches) so I could tell when the agent’s join logic was wrong. I kept comparison in a pure function so tests and the API share one code path, and I re-ran import + tests after each meaningful change.

### a. Name one thing the AI agent got wrong. How did you notice?

An early join on exact `record_ref` strings would have treated `rec1034`, ` REC - 1070 `, and `1112` as missing/orphan disagreements. I noticed by grepping the CSV refs and counting “missing” rows before vs after normalization — those three match cleanly once normalized and their values agree, so they are non-errors.

### b. Which part of your submission are you least confident about, and why?

Tenant scoping for edge cases where System A and System B disagree on `location_id` (and therefore possibly org). The brief’s required disagreements are value/presence based, so location drift is not flagged, but a stricter multi-tenant product would need an explicit rule for cross-org location mismatches.

### c. If you had a second day, what would you fix first?

Add an integration test that imports the real CSVs and asserts the exact disagreement set (ids + reasons) per org, so regressions in normalization or field choice (`total_value` vs `base_value`) are caught automatically.

## API sketch

- `GET /api/orgs/`
- `GET /api/disagreements/?org_id=ORG-A&reason=value_mismatch&ordering=value`

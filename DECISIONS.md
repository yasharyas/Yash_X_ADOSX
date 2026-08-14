# Decisions

1. **Compare System A `total_value` to System B `value`.**  
   Rejected: comparing `base_value`.  
   Reasoning: most matching rows agree on `total_value`; several mismatches are exactly A’s `base_value` written into B, which is the bug we should surface.

2. **Normalize messy `record_ref` values before matching.**  
   Rejected: exact string equality on `record_ref`.  
   Reasoning: dirty forms (`rec1034`, spaced `REC - 1070`, bare `1112`) still point at real A records and must not become false disagreements.

3. **Store raw CSV strings plus nullable parsed fields.**  
   Rejected: failing the import (or skipping the row) when a number/date will not parse.  
   Reasoning: the brief requires dirty rows to survive; parse issues are recorded, not discarded.

4. **Always flag duplicates, even when B values match each other and A.**  
   Rejected: only flagging duplicates when values also differ.  
   Reasoning: “entered twice” is its own disagreement class in the brief.

5. **Treat blank or unparseable B `value` as a value mismatch when A has a number.**  
   Rejected: ignoring blanks as “no data to compare.”  
   Reasoning: the systems do not agree on the amount; blank is still a reported disagreement.

6. **Scope API results with a required `org_id` query param (no auth).**  
   Rejected: returning the global list and filtering only in the UI.  
   Reasoning: tenant isolation must be enforced server-side so one org cannot see another’s rows.

7. **Use SQLite for the take-home database.**  
   Rejected: Postgres for “realism.”  
   Reasoning: zero setup for a clean clone; 120-row dataset does not need a server DB.

8. **Keep comparison in a pure function over plain data objects.**  
   Rejected: embedding the rules only inside DRF views/querysets.  
   Reasoning: the same logic is easy to unit test without HTTP or DB fixtures.

9. **Django REST + Vite React SPA instead of Next.js.**  
   Rejected: Next.js frontend.  
   Reasoning: clearer back/front split for a one-day feature, with a proxy for local `/api` calls.

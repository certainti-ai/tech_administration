# Recon check ledger

A running register of every value mismatch found between objects while mapping
the portfolio dashboard. The recon report/script is built **last**, from this
ledger — nothing here is executed yet.

Environment: **production**. All counts read-only, as at 2026-09-15.
Standing filters that apply to every check: exclude test accounts
(`account_name ILIKE '%-Test Account%'`), and require `account_rid` to exist in
the schema's `account_details` **and** in main `trd365.account` with an Active
status.

| # | Check | Objects | Rule | Observed |
|---|-------|---------|------|----------|
| R1 | Dangling case→fiscal FK | `case_projects.project_fiscal_rid` → `project_fiscal.rid` | every case project must resolve to a live `project_fiscal` row | **4,816 of 31,096 (15.5%) dangle**; 0 NULL; 0 duplicate FK |
| R2 | Case project-year uniqueness | `case_projects` | at most one row per `(project_rid, fiscal_year)` | **929 extra rows** — same project-year taken into more than one case |
| R3 | Account guard, fiscal side | `project_fiscal.account_rid` vs `account_details` + main `account` (Active) | every row must pass | **433 of 32,738 rows fail** |
| R4 | Account guard, case side | `case_projects.account_rid` vs same | every row must pass | 0 of 31,096 fail |
| R5 | Cost restatement | `case_projects.total_cost_prj` vs `project_fiscal.total_cost_prj` on matched `(project_rid, fiscal_year)` | should be identical — the case row is a snapshot | **712 of 27,862 differ**, net **−102.3M** native currency |
| R6 | Population containment | `case_projects` ⊂ `project_fiscal` | every case project-year exists in `project_fiscal` | **3,234 case rows have no matching project-year**; 5,796 fiscal rows never entered a case |
| R7 | Schema coverage | `project_fiscal` (30 schemas) vs `case_projects` (26) | tables should be co-present | **4 schemas carry `project_fiscal` but no `case_projects`** |
| R8 | Orphan schema | org schema `trd365_00582` | every `trd365_<digits>` schema maps to an `ACC-<digits>` row in main `account` | **no parent account row**; schema holds 9,903 projects |
| R9 | Unpopulated cost columns | `case_projects` | a column used as a KPI source must be broadly populated | `effective_cost` non-zero on **6 of 31,095**; `total_cost_from_tasks` on **263** |
| R10 | Cost column disagreement | `total_cost_prj` vs `total_cost_from_prj_res` | stated project cost vs resource rollup should reconcile | gap **569.3M USD (8.7%)** on `case_projects`; `total_cost_prj` NULL on 725 rows where the rollup has a value; rollup zero on 3,440 rows |
| R11 | Account rollup columns | main `trd365.account.total_projects / total_project_cost / qualifying_*` | should agree with the org-schema rollups | **not yet checked** |

## Notes on derivation

- Currency: every money figure is converted to USD via
  `trd365.currency_conversion` (`to_currency_code='USD'`) keyed on the row's
  `currency_rid` → `trd365.currency.currency_code`.
- `case_projects` carries `project_fiscal_rid`, so R1 is the authoritative
  containment test; R6 is the weaker `(project_rid, fiscal_year)` form and is
  kept because the two disagree.
- `account_details` has **no status column** — active state lives only on main
  `trd365.account.status_rid` → `trd365.status` (`Active` /  `In-Active`).
  Today all 71 accounts are Active, so the guard currently drops nobody on that
  clause; R3's 433 failures are missing `account_details` rows.

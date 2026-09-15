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
| R1 | Dangling case→fiscal FK | `case_projects.project_fiscal_rid` → `project_fiscal.rid` | every case project must resolve to a live `project_fiscal` row | **~4,880 of 31,096 (15.7%) dangle**; 0 NULL; 0 duplicate FK. **Count is growing** — 4,816 → 4,867 → 4,886 over ~20 min. Concentrated in **19 case / fiscal-year groups, 14 accounts, but only 7 tenant schemas** — whole case populations, not scattered rows |
| R2 | Case project-year uniqueness | `case_projects` | at most one row per `(project_rid, fiscal_year)` | **929 extra rows** — same project-year taken into more than one case |
| R3 | Account guard, fiscal side | `project_fiscal.account_rid` vs `account_details` + main `account` (Active) | every row must pass | **433 of 32,738 rows fail** |
| R4 | Account guard, case side | `case_projects.account_rid` vs same | every row must pass | 0 of 31,096 fail |
| R5 | Cost restatement | `case_projects.total_cost_prj` vs `project_fiscal.total_cost_prj` on matched `(project_rid, fiscal_year)` | should be identical — the case row is a snapshot | **712 of 27,862 differ**, net **−102.3M** native currency |
| R6 | Population containment | `case_projects` ⊂ `project_fiscal` | every case project-year exists in `project_fiscal` | **3,234 case rows have no matching project-year**; 5,796 fiscal rows never entered a case |
| R7 | Schema coverage | `project_fiscal` (30 schemas) vs `case_projects` (26) | tables should be co-present | **4 schemas carry `project_fiscal` but no `case_projects`** |
| R8 | Orphan schema | org schema `trd365_00582` | every `trd365_<digits>` schema maps to an `ACC-<digits>` row in main `account` | **no parent account row**; schema holds 9,903 projects |
| R9 | Unpopulated cost columns | `case_projects` | a column used as a KPI source must be broadly populated | `effective_cost` non-zero on **6 of 31,095**; `total_cost_from_tasks` on **263** |
| R10 | Cost column disagreement | `total_cost_prj` vs `total_cost_from_prj_res` | stated project cost vs resource rollup should reconcile | gap **569.3M USD (8.7%)** on `case_projects`; `total_cost_prj` NULL on 725 rows where the rollup has a value; rollup zero on 3,440 rows |
| R11 | Case header vs member rows | `cases.case_total_projects / case_total_project_cost / case_total_qualified_projects / case_total_qre_cost` | the case header must agree with the `case_projects` rows it owns | **not yet checked** |
| R12 | Account rollup columns | main `trd365.account.total_projects / total_project_cost / qualifying_*` | should agree with the org-schema rollups | **not yet checked** |

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

## R1 — root cause (evidenced)

The project-fiscal purge **never deletes `case_projects` rows**. Section 2 of
`project_fiscal/base_sql/02_delete_project_ORGDB_SECTION2.sql` (block `[O20b]`,
around line 672) only issues an `UPDATE` recomputing two type-agnostic totals
(`total_cost_from_prj_res`, `total_effort_from_prj_res`) for each linked case.
There is no `DELETE FROM ... case_projects` anywhere in the fiscal purge, so the
snapshot row survives its `project_fiscal` parent and its `project_fiscal_rid`
is left dangling.

Two consequences follow, and both are visible in production:

1. **Assessed cost exceeds loaded cost.** `case_projects` totals 6,548.1M USD
   against `project_fiscal`'s 6,204.8M, even though the assessed population is
   supposed to be a subset. The orphaned snapshots are the difference.
2. **The same purge leaves a documented partial recompute.** The per-resource-
   type breakdown (`total_cost_fte_from_prj_res`, `..._subcon_...`,
   `..._nonlabor_...`) is not recomputed, because the resource-type lookup lives
   in a different Postgres server and the SQL-only block cannot join across it.
   So even the surviving rows can disagree with their own type-agnostic totals —
   add this as a check when R5 is built out.

### Where it concentrates

Seven of the 26 schemas carrying `case_projects` hold every dangling row. One
schema alone holds 8 of the 19 groups (~45% of the rows) across six different
child accounts, and another holds three groups across two unrelated accounts.
The recon report should therefore group by **tenant schema first**, then by
account — the account view alone hides the concentration.

Note also that case numbers are minted per tenant schema, so `CHS-000000000`
recurs in five different schemas. A case is identified only by the
`(tenant_schema, case_number)` pair; any dashboard filter or recon key on case
number alone will collide.

Caveat worth holding: the dangling count is **rising while nothing is being
purged from this workstream**, so the purge explains the mechanism but is not
necessarily the only producer. The live application may also be writing
`case_projects` rows against `project_fiscal` rows it later replaces. Confirm
before attributing.

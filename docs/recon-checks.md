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
| R1 | Dangling case→fiscal FK | `case_projects.project_fiscal_rid` → `project_fiscal.rid` | every case project must resolve to a live `project_fiscal` row | **~4,880 of 31,096 (15.7%) dangle**; 0 NULL; 0 duplicate FK. **Count is growing** — 4,816 → 4,867 → 4,886 over ~20 min. Concentrated in **19 case / fiscal-year groups, 14 accounts, 7 tenant schemas**. **Not missing data** — these are stale links left by project re-loads; see the corrected root cause below |
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

## R1 — root cause (corrected 2026-09-15)

**Earlier attribution to the fiscal purge was wrong.** The purge gap is real —
`project_fiscal/base_sql/02_delete_project_ORGDB_SECTION2.sql` block `[O20b]`
only recomputes two totals on `case_projects` and never deletes the rows — but
it is not what produces these. **Re-loads are.**

A project re-load deletes and re-inserts `project` and `project_fiscal`. RIDs are
minted by the database (`gen_random_uuid()`) and never reused, so the new rows
carry new RIDs while the `case_projects` snapshot still holds the old ones. The
data is intact; only the links are stale. The application does not notice because
it resolves by `project_code`, not by RID.

### Worked example

Schema `trd365_00416`, case `P001-aeba7eac-2fb8-48ea-94c2-a7204509323f`,
`case_projects.rid = P001-897248c9-6632-4616-9f39-5fa99a5009ed`:

| | |
|---|---|
| project_code / FY | `Y.TI2300009` / 2025 |
| total_cost_prj | 50,543.23 |
| case row created | 2026-08-21 11:12:18 |
| `project_rid` | `P001-a91d1612-…` — absent from `project` |
| `project_fiscal_rid` | `P001-9ffbeacd-…` — absent from `project_fiscal` |

The live rows for that same code were created five days later, on
2026-08-26 15:55 — `project` `P001-8adaf4ce-…` (PRJ-0000009043) and
`project_fiscal` `P001-8fa062d2-…` (PFI-0000013921, FY2025), the latter carrying
**total_cost_prj 50,543.23, identical to the cent**. One
`case_project_resource` row still points at the dead `project_fiscal_rid`.

### Categories and repair keys

| category | rows | re-match key |
|---|---|---|
| stale fiscal pointer — `project` row still live | **1,961** | `(project_rid, fiscal_year)` |
| project RID moved too | **3,184** | `(account_rid, project_code, fiscal_year)` |
| unresolvable | **0** | — |

Of the second category, **3,099 resolve to exactly one live `project_fiscal`
row — no ambiguous matches, none unmatched** — and 2,518 of those agree on cost
to the cent. The recon report should therefore classify rather than simply count:
a stale link is not missing data, and every row here is repairable from data
already present.

### Still open

The `case_projects` cost exceeding `project_fiscal` cost (6,548.1M vs 6,204.8M
USD) is **not** explained by orphaned snapshots, since nothing is orphaned. The
929 duplicate `(project_rid, fiscal_year)` rows of R2 are the likelier cause.
Do not restate the earlier explanation — verify this one first.

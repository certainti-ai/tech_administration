# Standing rules

Rules the user has given that apply to **all** work in this workstream, not just
the task they were given in. Append here as new ones arrive; never drop one
because a task is finished.

## 1. Repository and data safety

| # | Rule |
|---|------|
| 1.1 | `certainti-ai/incentiwise-beta` is **out of scope, absolutely** — not read, cloned, referenced, quoted, or used as precedent or comparison, from the repo or from recollection. If something cannot be answered without it, say so and stop. |
| 1.2 | **No INSERT / UPDATE / DELETE on any application database.** Read-only always. |
| 1.3 | No data change of any kind without explicit approval, per change. |
| 1.4 | Nothing is run without approval. |
| 1.5 | No changes to any existing product repo or database. |
| 1.6 | `legacy/trd365_maintenance/` is reference material — never edited in place. |
| 1.7 | Never print a secret value. Secrets tooling reports 12-char SHA-256 digests only. |
| 1.8 | Never disable TLS verification, never unset `HTTPS_PROXY`, never route around a 403/407 policy denial — report it. |

## 2. Git

| # | Rule |
|---|------|
| 2.1 | Develop, commit and push **only** to `claude/certainti-tech-admin-y4c4ul`. Never another branch without permission. |
| 2.2 | Never open a pull request unless explicitly asked. |
| 2.3 | No model identifier in any commit message, PR body, code comment, or other pushed artifact. |

## 3. Deliverables — what may and may not appear

| # | Rule |
|---|------|
| 3.1 | **No real customer names** (e.g. no named client organisations). Use neutral placeholders. |
| 3.2 | **No real database, schema or component names** in investor/technical deliverables. |
| 3.3 | **No hosted-model vendor named, ever.** All inference reads as **"self-hosted"**. No Azure OpenAI reference anywhere. |
| 3.4 | No Anthropic/Claude, Gemini, Bedrock or Cohere is present in the platform — never imply otherwise. |
| 3.5 | Ontario is **Canadian**. Never list it under the US states. US sub-federal = 26 states + DC = 27; Canada = Ontario. |
| 3.6 | Font is **Poppins**. Never Bold (700) — use Semi-Bold (600). For the Stack & IP document: Normal (400) and Medium (500) only. |
| 3.7 | Diagram connectors are **soft curved** with arrowheads square to the target face. |
| 3.8 | Assert nothing as architecture that is not in the code. Numbers sourced from the ingested PDF are flagged as unverified, not stated as fact. |

## 4. Portfolio dashboard — data rules

| # | Rule |
|---|------|
| 4.1 | **Exclude test accounts from every metric.** Production has one, identified by `account_name ILIKE '%-Test Account%'` (case-insensitive). The team will keep naming test accounts that way. |
| 4.2 | **Project count and project cost come from two populations, reported separately:** `project` / `project_fiscal` = everything loaded; `case_projects` = only what was taken into a case for R&D assessment. Not every loaded project qualifies, so the two must never be conflated. |
| 4.3 | **Every SQL must validate the account.** `account_rid` must exist in the org schema's `account_details` **and** in main `trd365.account` with an **Active** status. |
| 4.4 | Money is converted to USD via `trd365.currency_conversion` (`to_currency_code='USD'`), keyed off the row's `currency_rid` → `trd365.currency.currency_code`. |

## 5. Working method

| # | Rule |
|---|------|
| 5.1 | Field mapping is decided **metric by metric**: bring candidate values from the database, the user decides which column to lock in. |
| 5.2 | Do not use the Agent tool, workflows, or deep research unless explicitly asked. |
| 5.3 | Keep this file current — the user will add more rules as the work progresses. |

## 6. Recon report

| # | Rule |
|---|------|
| 6.1 | A **recon report** is being built in parallel, highlighting value mismatches between objects. Every mismatch and its logic is logged in `docs/recon-checks.md` as it is found; the script itself is written last. |

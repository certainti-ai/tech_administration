#!/usr/bin/env node
'use strict';

/**
 * Manual R&D percent update tool.
 *
 * Reproduces, byte-for-byte, the write path the application executes when a
 * user adjusts a project's R&D percentage through the entity-module GraphQL
 * mutation `updateQreAdjustment`. That mutation resolves to:
 *   - entity-module/src/services/projectService.ts        updateQrePercentAdjustment()
 *   - entity-module/src/services/schemaService.ts          updateQreAdjustmentCalculation()
 *   - entity-module/src/services/schemaService.ts          insertQreAdjustmentHistory()
 *
 * Why a Node script and not a plain .sql file: the platform's Main DB
 * (schema `trd365`: account, status, case_status, user, event_types,
 * project_fiscal_summary) and Org DB (per-tenant schema `trd365_<n>`:
 * project_fiscal, project_resource_fiscal, cases, case_projects,
 * case_project_resource_fiscal, project_qre_adjustment_history,
 * project_timeline) are separate Postgres server instances in this
 * deployment. A single SQL script/transaction cannot span both. The
 * application itself does not use a distributed transaction across them
 * either -- it just awaits two sequelize connections in sequence -- so this
 * script mirrors that: one transaction on the Org DB, one transaction on
 * the Main DB, run in the same order the app runs them, per record. If the
 * Org DB transaction for a record commits and the Main DB transaction then
 * fails, you are in exactly the same partial-write state the application
 * itself could leave you in; the Main DB step is idempotent (same WHERE
 * key, same computed values), so re-running just that record is safe.
 *
 * IMPORTANT semantic note on inputs (verified against the GraphQL schema at
 * entity-module/src/graphql/projectSchema.ts `QreAdjustmentInput` and the
 * resolver at entity-module/src/services/projectService.ts:2593):
 * the field the application calls `rd_percent_potential_ai` in that mutation
 * is NOT the AI-generated potential percentage -- it is used purely as the
 * *delta* added to whatever `rd_percent_potential_ai` is already stored on
 * project_fiscal to produce `rd_percent_final`. The app never rewrites
 * project_fiscal.rd_percent_potential_ai through this path.
 *
 * This tool accepts all three percentages explicitly (as requested) because
 * the intent here is to simulate "AI potential was just generated AND the
 * adjustment was just applied" as a single manual operation. Concretely:
 *   - rd_percent_potential_ai : written to project_fiscal.rd_percent_potential_ai
 *     (this is the one place this script does MORE than the live app does,
 *     because the app has no single endpoint that writes this column and
 *     applies an adjustment in the same call).
 *   - rd_percent_adjustment   : the delta, written exactly where the app
 *     writes it (project_fiscal, project_resource_fiscal, case_projects,
 *     case_project_resource_fiscal, project_fiscal_summary, and the
 *     project_qre_adjustment_history audit row).
 *   - rd_percent_final        : must equal
 *     round2(rd_percent_potential_ai + rd_percent_adjustment) -- this is the
 *     app's derivation rule (schemaService.ts:4244, `netQre`). The script
 *     verifies your three inputs are internally consistent with that rule
 *     and refuses to run otherwise, because writing an inconsistent final
 *     value would NOT reproduce a state the application could ever produce.
 *
 * ---------------------------------------------------------------------------
 * Connection info: no .env file -- edit the DB_CONFIG block in db-config.js
 * (shared with rollback.js) with the real Main DB / Org DB host, port,
 * database, user, password.
 * ---------------------------------------------------------------------------
 * Usage -- single record:
 *   node index.js \
 *     --account-id <account_id> \
 *     --project-code <project_code> \
 *     --fiscal-year <fiscal_year> \
 *     --rd-percent-potential-ai <number> \
 *     --rd-percent-adjustment <number> \
 *     --rd-percent-final <number> \
 *     [--comments "free text"] \
 *     [--dry-run]
 *
 * Usage -- batch from CSV (see sample-input.csv):
 *   node index.js --csv sample-input.csv [--dry-run]
 *
 * CSV columns (header row required, any order):
 *   account_id, project_code, fiscal_year, rd_percent_potential_ai,
 *   rd_percent_adjustment, rd_percent_final, comments
 * `comments` may be blank. Quote any field containing a comma.
 *
 * account_id is the account's human-facing Account ID (the `r_number`
 * column on trd365.account) -- NOT the internal account_rid. This tool
 * resolves account_rid itself: SELECT rid, ... FROM trd365.account WHERE
 * r_number = <account_id> -- see resolveAccount. Every downstream
 * account_rid column reference (project_fiscal lookup, the timeline entry,
 * the qre_adjustment_history row) uses that resolved account_rid, not the
 * account_id you provided.
 *
 * project_fiscal_rid is resolved internally from account_rid + project_code
 * + fiscal_year (SELECT rid FROM project_fiscal WHERE account_rid = ...
 * AND project_code = ... AND fiscal_year = ...) -- see resolveProjectFiscal.
 *
 * user_rid is NOT an input: every audit column (modified_by, created_by,
 * the timeline entry, the qre_adjustment_history row) is hardcoded to the
 * literal string "system" (constant SYSTEM_USER_RID below), since this tool
 * runs outside any real user's session.
 *
 * Each row is processed independently (its own Org DB transaction + Main DB
 * transaction) -- one bad row does not abort the rest of the batch.
 *
 * An output CSV is ALWAYS written (single-record mode too), one row per
 * input record, with:
 *   - status : exactly "success" or "failed"
 *   - error  : the raised error message when status is "failed" (blank otherwise)
 *   - dry_run: "true"/"false", recorded separately so status stays strictly
 *              success/failed even on a --dry-run pass
 * File name: `<input>.results.<timestamp>.csv` next to the input CSV in
 * batch mode, or `output.results.<timestamp>.csv` in the current directory
 * in single-record mode.
 *
 * Backups: before ANY row is modified, this script snapshots it (the full
 * row, as JSONB) into a `manual_rd_percent_backup` table -- one such table
 * per Org DB tenant schema that gets touched, and one in the Main DB
 * (`trd365.manual_rd_percent_backup`). Every row this run backs up is
 * tagged with the same run_id (printed at startup, e.g. "run-2026-07-20T..-abcd12").
 * The backup insert for a given row happens inside the SAME transaction as
 * the update that follows it, so a backup and its corresponding change
 * always commit or roll back together -- no orphaned backups for changes
 * that never actually happened.
 *
 * To roll back an entire run (every row it modified, across however many
 * tenant schemas plus the Main DB), use the companion script:
 *   node rollback.js --run-id <run_id>          # preview only
 *   node rollback.js --run-id <run_id> --yes    # actually restore
 * See rollback.js's header comment for details. To inspect backups without
 * restoring anything:
 *   SELECT * FROM "<schema>".manual_rd_percent_backup WHERE run_id = '<run_id>';
 * ---------------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { Client } = require('pg');
const {
  MAIN_SCHEMA_NAME, SCHEMANAME_PREFIX, RID_PREFIX, BACKUP_TABLE_NAME,
  openTunnels, mainClientConfig, orgClientConfig,
} = require('./db-config');

// Hardcoded per instruction: this tool has no real logged-in user, so every
// audit column (project_fiscal.modified_by, project_resource_fiscal /
// case_projects / case_project_resource_fiscal / project_fiscal_summary
// modified_by, the project_timeline created_by, and the
// project_qre_adjustment_history created_by) uses this literal value.
const SYSTEM_USER_RID = 'system';

const REQUIRED_FIELDS = [
  'accountId', 'projectCode', 'fiscalYear', 'rdPercentPotentialAi',
  'rdPercentAdjustment', 'rdPercentFinal',
];

// ---------------------------------------------------------------------------
// CLI parsing
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const out = { dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--csv': out.csv = argv[++i]; break;
      case '--account-id': out.accountId = argv[++i]; break;
      case '--project-code': out.projectCode = argv[++i]; break;
      case '--fiscal-year': out.fiscalYear = argv[++i]; break;
      case '--rd-percent-potential-ai': out.rdPercentPotentialAi = argv[++i]; break;
      case '--rd-percent-adjustment': out.rdPercentAdjustment = argv[++i]; break;
      case '--rd-percent-final': out.rdPercentFinal = argv[++i]; break;
      case '--comments': out.comments = argv[++i]; break;
      case '--dry-run': out.dryRun = true; break;
      default:
        throw new Error(`Unknown argument: ${a}`);
    }
  }

  if (out.csv) {
    return out;
  }

  const missing = REQUIRED_FIELDS.filter((k) => out[k] === undefined || out[k] === '');
  if (missing.length) {
    throw new Error(
      `Missing required argument(s): ${missing.join(', ')} (or pass --csv <file> for batch mode)`
    );
  }
  return out;
}

function round2(n) {
  return Math.round((Number(n) + Number.EPSILON) * 100) / 100;
}

// ---------------------------------------------------------------------------
// Minimal RFC4180 CSV parsing (quoted fields, embedded commas/quotes/newlines)
// No external dependency -- the input shape here is simple enough that a
// small hand-rolled parser is more auditable than pulling in a csv package.
// ---------------------------------------------------------------------------

function parseCsv(content) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  const text = content.replace(/\r\n/g, '\n');

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += c;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const nonEmptyRows = rows.filter((r) => !(r.length === 1 && r[0].trim() === ''));
  if (nonEmptyRows.length === 0) return [];

  const header = nonEmptyRows[0].map((h) => h.trim().toLowerCase());
  return nonEmptyRows.slice(1).map((r) => {
    const obj = {};
    header.forEach((h, idx) => { obj[h] = (r[idx] !== undefined ? r[idx] : '').trim(); });
    return obj;
  });
}

function toCsvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

// Always writes an output CSV -- one row per input record -- with a
// status column of exactly 'success' or 'failed', and the error message
// (if any) in the error column. Written whether the run used --csv batch
// mode or the single-record flags, and whether or not --dry-run was set
// (a dry_run column records that separately so status stays strictly
// success/failed as requested).
function writeResultsCsv(baseNameHint, results) {
  const header = [
    'account_id', 'project_code', 'fiscal_year', 'project_fiscal_rid',
    'rd_percent_potential_ai', 'rd_percent_adjustment', 'rd_percent_final',
    'comments', 'status', 'error', 'dry_run', 'run_id',
  ];
  const lines = [header.join(',')];
  for (const r of results) {
    lines.push([
      r.record.accountId, r.record.projectCode, r.record.fiscalYear,
      r.resolvedProjectFiscalRid || '', r.record.rdPercentPotentialAi,
      r.record.rdPercentAdjustment, r.record.rdPercentFinal,
      r.record.comments || '', r.status, r.error || '', r.dryRun ? 'true' : 'false',
      r.runId || '',
    ].map(toCsvField).join(','));
  }

  const dir = baseNameHint ? path.dirname(baseNameHint) : process.cwd();
  const base = baseNameHint
    ? path.basename(baseNameHint, path.extname(baseNameHint))
    : 'output';
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outPath = path.join(dir, `${base}.results.${stamp}.csv`);
  fs.writeFileSync(outPath, lines.join('\n') + '\n', 'utf8');
  return outPath;
}

// Lists every backup table this run wrote into -- one row per (db, schema,
// table_name) combination that received at least one snapshot row, plus how
// many rows. This is what tells you what's left to clean up afterward: once
// you've confirmed the update is correct and no longer need rollback
// capability, use cleanup-backups.js against these same schemas (--run-id
// to delete just this run's rows, --drop-tables to remove the backup
// tables entirely across all runs).
function writeBackupManifestCsv(baseNameHint, runId, backupState) {
  const header = ['run_id', 'db', 'schema', 'table_name', 'rows_backed_up'];
  const lines = [header.join(',')];
  for (const [key, count] of Object.entries(backupState.counts)) {
    const [db, schema, tableName] = key.split('|');
    lines.push([runId, db, schema, tableName, count].map(toCsvField).join(','));
  }

  const dir = baseNameHint ? path.dirname(baseNameHint) : process.cwd();
  const base = baseNameHint
    ? path.basename(baseNameHint, path.extname(baseNameHint))
    : 'output';
  const outPath = path.join(dir, `${base}.backup-manifest.${runId}.csv`);
  fs.writeFileSync(outPath, lines.join('\n') + '\n', 'utf8');
  return outPath;
}

function loadRecordsFromCsv(csvPath) {
  const content = fs.readFileSync(csvPath, 'utf8');
  const rawRows = parseCsv(content);
  const fieldMap = {
    account_id: 'accountId',
    project_code: 'projectCode',
    fiscal_year: 'fiscalYear',
    rd_percent_potential_ai: 'rdPercentPotentialAi',
    rd_percent_adjustment: 'rdPercentAdjustment',
    rd_percent_final: 'rdPercentFinal',
    comments: 'comments',
  };
  return rawRows.map((raw, idx) => {
    const record = {};
    for (const [csvKey, propKey] of Object.entries(fieldMap)) {
      record[propKey] = raw[csvKey] !== undefined ? raw[csvKey] : '';
    }
    const missing = REQUIRED_FIELDS.filter((k) => record[k] === undefined || record[k] === '');
    if (missing.length) {
      throw new Error(`CSV row ${idx + 2}: missing required column(s): ${missing.join(', ')}`);
    }
    return record;
  });
}

// ---------------------------------------------------------------------------
// Step 1 (Main DB, read-only) -- resolve the account (by r_number, i.e. the
// external "Account ID" the user supplies -- NOT the internal account_rid)
// and from it the tenant schema. Mirrors
// projectService.ts:updateQrePercentAdjustment (lines 2603-2638) and
// schemaService.ts:checkIfSchemaExists, except the app's own entry point
// takes account_rid directly (from an already-authenticated session) where
// this tool takes the human-facing r_number and resolves account_rid itself.
// ---------------------------------------------------------------------------

async function resolveAccount(mainClient, accountId) {
  const { rows } = await mainClient.query(
    `SELECT a.rid, a.r_number, a.parent_account_rid, a.storage_type,
            s.status_description AS status
     FROM ${MAIN_SCHEMA_NAME}.account a
     LEFT JOIN ${MAIN_SCHEMA_NAME}.status s ON a.status_rid = s.rid
     WHERE a.r_number = $1`,
    [accountId]
  );
  const account = rows[0];
  if (!account) {
    throw new Error(`Invalid Account ID: no account found for r_number=${accountId}`);
  }
  // Mirrors: if (accountData.status !== "active") throw ...
  if (account.status !== 'active') {
    throw new Error(
      'Project creation failed: The selected account is inactive. Please choose an active account.'
    );
  }
  // Mirrors: if (parent_account_rid === null || parent_account_rid === "") throw ...
  // This is a real (if unintuitive) guard in the live app: the QRE-adjustment
  // path refuses to run for an account with no parent_account_rid.
  if (account.parent_account_rid === null || account.parent_account_rid === '') {
    throw new Error('Error creating project: Invalid account ID');
  }

  let accountNumber = account.r_number;

  // Mirrors: if (accountData.storage_type === "store_in_parent") -> use parent's r_number
  if (account.storage_type === 'store_in_parent') {
    const parentRes = await mainClient.query(
      `SELECT r_number FROM ${MAIN_SCHEMA_NAME}.account WHERE rid = $1`,
      [account.parent_account_rid]
    );
    accountNumber = parentRes.rows[0] && parentRes.rows[0].r_number;
    if (!accountNumber) {
      throw new Error('Error fetching parent account: parent account not found');
    }
  }

  const schemaName = `${SCHEMANAME_PREFIX}${String(accountNumber).replace(/\D/g, '')}`;
  // Defensive allow-list check before this value is ever interpolated into
  // a schema-qualified identifier below (it is derived from a DB column,
  // not directly from CLI input, but we never trust interpolated
  // identifiers without validating their shape first).
  if (!/^trd365_[0-9]+$/.test(schemaName)) {
    throw new Error(`Resolved schema name looks invalid: ${schemaName}`);
  }
  // accountRid (account.rid) is the account the project actually belongs to
  // -- used for every downstream account_rid column reference -- which is
  // NOT necessarily the same account whose r_number built the schema name
  // above (that can be the parent, under store_in_parent).
  return { schemaName, accountRid: account.rid };
}

async function checkSchemaExists(orgClient, schemaName) {
  const { rows } = await orgClient.query(
    `SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)`,
    [schemaName]
  );
  return rows[0].exists;
}

async function checkTableExists(client, schemaName, tableName) {
  const { rows } = await client.query(
    `SELECT EXISTS (
       SELECT 1 FROM information_schema.tables
       WHERE table_schema = $1 AND table_name = $2
     )`,
    [schemaName, tableName]
  );
  return rows[0].exists;
}

// Resolves the project_fiscal row from account_rid + project_code +
// fiscal_year (returns the full row, since the caller needs total_cost_*
// columns too, not just rid). Mirrors the natural-key lookup pattern used
// elsewhere in the app (e.g.
// entity-module/src/utils/constants.ts:checkForDuplicateFiscalYear), which
// scopes project_code/fiscal_year matches by account_rid -- project_code is
// only unique within a single account's fiscal year, not globally.
async function resolveProjectFiscal(orgClient, schemaName, accountRid, projectCode, fiscalYear) {
  const { rows } = await orgClient.query(
    `SELECT * FROM "${schemaName}".project_fiscal
     WHERE account_rid = $1 AND project_code = $2 AND fiscal_year = $3`,
    [accountRid, projectCode, fiscalYear]
  );
  if (rows.length === 0) {
    throw new Error(
      `No project_fiscal row found for account_rid=${accountRid}, project_code=${projectCode}, fiscal_year=${fiscalYear}`
    );
  }
  if (rows.length > 1) {
    throw new Error(
      `Ambiguous lookup: ${rows.length} project_fiscal rows found for account_rid=${accountRid}, ` +
      `project_code=${projectCode}, fiscal_year=${fiscalYear} -- expected exactly one.`
    );
  }
  return rows[0];
}

// ---------------------------------------------------------------------------
// Backup helpers -- see the "Backups" section in the header comment.
// ---------------------------------------------------------------------------

// Creates the row-snapshot table in the given schema if it doesn't already
// exist. Run as its own auto-committed statement (NOT inside the record's
// write transaction) so the table itself persists even if that record's
// transaction later rolls back -- only the actual snapshot ROWS are
// transactional with their corresponding update (see backupRows below).
async function ensureBackupTable(client, tableIdent) {
  await client.query(`
    CREATE TABLE IF NOT EXISTS ${tableIdent} (
      id BIGSERIAL PRIMARY KEY,
      run_id TEXT NOT NULL,
      table_name TEXT NOT NULL,
      row_rid TEXT NOT NULL,
      row_data JSONB NOT NULL,
      backed_up_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);
}

// Accumulates how many rows were backed up per (db, schema, table_name),
// so a manifest of every backup table touched this run can be written out
// at the end (see writeBackupManifestCsv). dbLabel is 'org' or 'main'.
function trackBackup(backupState, dbLabel, schemaName, tableName, rowCount) {
  if (!rowCount) return;
  const key = `${dbLabel}|${schemaName}|${tableName}`;
  backupState.counts[key] = (backupState.counts[key] || 0) + rowCount;
}

// ---------------------------------------------------------------------------
// Per-record processing -- this is the full traced business logic.
// ---------------------------------------------------------------------------

async function processRecord(mainClient, orgClient, record, { dryRun, runId, backupState }) {
  // --- Step 1: resolve the account (by r_number) + tenant schema (Main DB,
  // read-only). accountRid here is the resolved internal account_rid, used
  // for every downstream account_rid column reference.
  const { schemaName, accountRid } = await resolveAccount(mainClient, record.accountId);
  console.log(`[resolve] account_id=${record.accountId} -> account_rid=${accountRid}, schema=${schemaName}`);

  if (!(await checkSchemaExists(orgClient, schemaName))) {
    throw new Error("Invalid Account ID: schema doesn't exists");
  }

  // --- Step 2: resolve project_fiscal from account_rid + project_code +
  // fiscal_year (Org DB, read-only). See resolveProjectFiscal's comment for
  // why this natural key is scoped by account_rid.
  const fiscalYear = parseInt(record.fiscalYear, 10);
  if (!Number.isInteger(fiscalYear)) {
    throw new Error(`fiscal_year must be a valid integer, got "${record.fiscalYear}"`);
  }
  const projectFiscal = await resolveProjectFiscal(
    orgClient, schemaName, accountRid, record.projectCode, fiscalYear
  );
  const projectFiscalRid = projectFiscal.rid;
  console.log(`[resolve] project_code=${record.projectCode} fiscal_year=${fiscalYear} -> project_fiscal_rid=${projectFiscalRid}`);

  // --- Step 3: validate + compute, mirroring the app's netQre math ---------
  // schemaService.ts:4239-4256:
  //   existingPercent = projectFiscalDetails.rd_percent_potential_ai ?? 0
  //   parsedPercent = parseFloat(existingPercent)
  //   guard: parsedPercent must be a valid number >= 0
  //   netQre = qreAdjustment + parseFloat(existingPercent)
  //   qre_final/fte/subcon/nonlabor = total_cost_* * (netQre / 100)
  //   is_qualified = netQre > 0
  //
  // Here "existingPercent" is the rd_percent_potential_ai value THIS SCRIPT
  // is about to write (we are simulating that it was just generated), so
  // we validate the input itself rather than a pre-existing DB value.
  const potentialAi = Number(record.rdPercentPotentialAi);
  if (!Number.isFinite(potentialAi) || potentialAi < 0) {
    throw new Error(
      `rd_percent_potential_ai must be a valid number >= 0 (guard mirrors ` +
      `schemaService.ts:4243). Refusing to run rather than silently no-op ` +
      `the way the live endpoint does.`
    );
  }
  const adjustment = Number(record.rdPercentAdjustment);
  if (!Number.isFinite(adjustment)) {
    throw new Error('rd_percent_adjustment must be a valid number');
  }
  const netQre = round2(potentialAi + adjustment);
  const finalInput = round2(Number(record.rdPercentFinal));
  if (!Number.isFinite(finalInput)) {
    throw new Error('rd_percent_final must be a valid number');
  }
  if (Math.abs(netQre - finalInput) > 0.01) {
    throw new Error(
      `rd_percent_final (${finalInput}) does not equal rd_percent_potential_ai ` +
      `+ rd_percent_adjustment (${potentialAi} + ${adjustment} = ${netQre}). ` +
      `The application always derives rd_percent_final this way ` +
      `(schemaService.ts:4244) -- writing an inconsistent value here would ` +
      `produce a database state the app itself could never produce.`
    );
  }

  const totalCost = Number(projectFiscal.total_cost_prj) || 0;
  const totalFteCost = Number(projectFiscal.total_cost_fte_prj) || 0;
  const totalSubconCost = Number(projectFiscal.total_cost_subcon_prj) || 0;
  const totalNonlaborCost = Number(projectFiscal.total_cost_nonlabor_prj) || 0;

  const qreFinalCost = totalCost * (netQre / 100);
  const qreFteCost = totalFteCost * (netQre / 100);
  const qreSubconCost = totalSubconCost * (netQre / 100);
  const qreNonlaborCost = totalNonlaborCost * (netQre / 100);
  const isQualified = netQre > 0;

  console.log('[compute]', {
    schemaName, netQre, qreFinalCost, qreFteCost, qreSubconCost, qreNonlaborCost, isQualified,
  });

  // --- Step 4: closed-case status lookup (Main DB, read-only) ---------------
  // Mirrors rawQueries.fetchCaseClosedStatusRid(): note the app takes
  // closedCaseId?.[0]?.[0]?.rid -- i.e. an arbitrary first row with no
  // ORDER BY if multiple case_status rows match '%closed%'. Replicated
  // as-is (LIMIT 1, no ORDER BY) for identical behavior, not because it's
  // guaranteed deterministic.
  const closedStatusRes = await mainClient.query(
    `SELECT rid FROM ${MAIN_SCHEMA_NAME}.case_status WHERE status_name ILIKE '%closed%' LIMIT 1`
  );
  const closedStatusRid = closedStatusRes.rows[0] && closedStatusRes.rows[0].rid;

  // --- Step 5: user + event info for the audit timeline (Main DB, read) ----
  // Mirrors schemaService.ts:fetchUserAndEventInfo.
  const userEventRes = await mainClient.query(
    `SELECT
       (SELECT CONCAT(first_name, ' ', last_name) FROM ${MAIN_SCHEMA_NAME}."user" WHERE rid = $1 LIMIT 1) AS full_name,
       (SELECT rid FROM ${MAIN_SCHEMA_NAME}.event_types WHERE event_type_name = $2 LIMIT 1) AS event_type_rid`,
    [SYSTEM_USER_RID, 'web'] // eventTypes.UI_HANDLER
  );
  const { full_name: createdByName, event_type_rid: eventTypeRid } = userEventRes.rows[0] || {};

  if (dryRun) {
    console.log('[dry-run] All reads resolved successfully; no writes performed.');
    return { projectFiscalRid };
  }

  // --- Backup table setup (Org DB schema + Main DB), each ensured at most
  // once per script invocation. Own auto-committed statements, outside any
  // record's write transaction -- see ensureBackupTable's comment. ---------
  const orgBackupTable = `"${schemaName}".${BACKUP_TABLE_NAME}`;
  const mainBackupTable = `${MAIN_SCHEMA_NAME}.${BACKUP_TABLE_NAME}`;
  if (!backupState.orgSchemasEnsured.has(schemaName)) {
    await ensureBackupTable(orgClient, orgBackupTable);
    backupState.orgSchemasEnsured.add(schemaName);
  }
  if (!backupState.mainEnsured) {
    await ensureBackupTable(mainClient, mainBackupTable);
    backupState.mainEnsured = true;
  }

  // ===========================================================================
  // Step 6: Org DB writes, one transaction.
  // Mirrors, in order: updateProjectFiscalQre, updateProjectResourceFiscalQre,
  // checkTableExists('cases'), updateCaseProjectsQre (conditional),
  // checkIsProjectMapped, checkTableExists('case_project_resource_fiscal'),
  // updateCaseProjectResourceFiscalQre (conditional), insertProjectTimeLine,
  // and (from the separate insertQreAdjustmentHistory call) the
  // project_qre_adjustment_history insert.
  //
  // Every UPDATE below is preceded by a backup-snapshot INSERT capturing the
  // exact row(s) about to be overwritten, in the same transaction, so backup
  // and mutation always commit or roll back together (see header comment).
  // ===========================================================================
  await orgClient.query('BEGIN');
  try {
    // 6a. project_fiscal -- the one place this script writes
    // rd_percent_potential_ai, which the live endpoint never touches (see
    // header note). Everything else here matches updateProjectFiscalQre.
    const pfBackupRes = await orgClient.query(
      `INSERT INTO ${orgBackupTable} (run_id, table_name, row_rid, row_data)
       SELECT $1, $2, t.rid, to_jsonb(t)
       FROM "${schemaName}".project_fiscal t
       WHERE t.rid = $3`,
      [runId, 'project_fiscal', projectFiscalRid]
    );
    trackBackup(backupState, 'org', schemaName, 'project_fiscal', pfBackupRes.rowCount);
    await orgClient.query(
      `UPDATE "${schemaName}".project_fiscal
       SET rd_percent_potential_ai = $1,
           rd_percent_adjustment = $2,
           rd_percent_final = $3,
           qre_final = $4,
           qre_fte = $5,
           qre_subcon = $6,
           qre_nonlabor = $7,
           modified_by = $8,
           modified_datetime = now(),
           is_qualified = $9
       WHERE rid = $10`,
      [potentialAi, adjustment, netQre, qreFinalCost, qreFteCost, qreSubconCost,
       qreNonlaborCost, SYSTEM_USER_RID, isQualified, projectFiscalRid]
    );

    // 6b. project_resource_fiscal -- matches updateProjectResourceFiscalQre
    // exactly (no rd_percent_potential_ai, no is_qualified column write --
    // the live app does not set either of those here).
    const prfBackupRes = await orgClient.query(
      `INSERT INTO ${orgBackupTable} (run_id, table_name, row_rid, row_data)
       SELECT $1, $2, t.rid, to_jsonb(t)
       FROM "${schemaName}".project_resource_fiscal t
       WHERE t.project_fiscal_rid = $3`,
      [runId, 'project_resource_fiscal', projectFiscalRid]
    );
    trackBackup(backupState, 'org', schemaName, 'project_resource_fiscal', prfBackupRes.rowCount);
    await orgClient.query(
      `UPDATE "${schemaName}".project_resource_fiscal
       SET rd_percent_adjustment = $1,
           rd_percent_final = $2,
           qre_final = $3,
           qre_fte = $4,
           qre_subcon = $5,
           qre_nonlabor = $6,
           modified_by = $7,
           modified_datetime = now()
       WHERE project_fiscal_rid = $8`,
      [adjustment, netQre, qreFinalCost, qreFteCost, qreSubconCost,
       qreNonlaborCost, SYSTEM_USER_RID, projectFiscalRid]
    );

    // 6c. Case-module tables are optional per tenant -- only touched if
    // the 'cases' table exists in this schema (checkTableExists default).
    const hasCasesTable = await checkTableExists(orgClient, schemaName, 'cases');
    if (hasCasesTable && closedStatusRid) {
      // Backup covers exactly the rows the following UPDATE will touch --
      // same join/filter, so only non-closed-case rows get snapshotted.
      const cpBackupRes = await orgClient.query(
        `INSERT INTO ${orgBackupTable} (run_id, table_name, row_rid, row_data)
         SELECT $1, $2, cp.rid, to_jsonb(cp)
         FROM "${schemaName}".case_projects cp
         JOIN "${schemaName}".cases c ON cp.case_rid = c.rid
         WHERE cp.project_fiscal_rid = $3 AND c.status_rid <> $4`,
        [runId, 'case_projects', projectFiscalRid, closedStatusRid]
      );
      trackBackup(backupState, 'org', schemaName, 'case_projects', cpBackupRes.rowCount);
      // Only updates case_projects rows attached to a NON-closed case.
      await orgClient.query(
        `UPDATE "${schemaName}".case_projects cp
         SET qre_fte = $1,
             qre_subcon = $2,
             qre_nonlabor = $3,
             qre_final = $4,
             rd_percent_adjustment = $5,
             rd_percent_final = $6,
             modified_by = $7,
             modified_datetime = now()
         FROM "${schemaName}".cases c
         WHERE cp.case_rid = c.rid
           AND cp.project_fiscal_rid = $8
           AND c.status_rid <> $9`,
        [qreFteCost, qreSubconCost, qreNonlaborCost, qreFinalCost, adjustment,
         netQre, SYSTEM_USER_RID, projectFiscalRid, closedStatusRid]
      );

      // Only touch case_project_resource_fiscal if this project is NOT
      // mapped to any CLOSED case at all (closed-case financials are
      // frozen by design -- matches checkIsProjectMapped's usage).
      const mappedRes = await orgClient.query(
        `SELECT c.rid, cp.project_fiscal_rid
         FROM "${schemaName}".cases c
         LEFT JOIN "${schemaName}".case_projects cp ON cp.case_rid = c.rid
         WHERE cp.project_fiscal_rid = $1
           AND c.status_rid = $2
         GROUP BY c.rid, cp.project_fiscal_rid`,
        [projectFiscalRid, closedStatusRid]
      );

      if (mappedRes.rowCount === 0) {
        const hasCaseResourceFiscalTable = await checkTableExists(
          orgClient, schemaName, 'case_project_resource_fiscal'
        );
        if (hasCaseResourceFiscalTable) {
          const cprfBackupRes = await orgClient.query(
            `INSERT INTO ${orgBackupTable} (run_id, table_name, row_rid, row_data)
             SELECT $1, $2, t.rid, to_jsonb(t)
             FROM "${schemaName}".case_project_resource_fiscal t
             WHERE t.project_fiscal_rid = $3`,
            [runId, 'case_project_resource_fiscal', projectFiscalRid]
          );
          trackBackup(backupState, 'org', schemaName, 'case_project_resource_fiscal', cprfBackupRes.rowCount);
          await orgClient.query(
            `UPDATE "${schemaName}".case_project_resource_fiscal
             SET rd_percent_adjustment = $1,
                 rd_percent_final = $2,
                 qre_final = $3,
                 qre_fte = $4,
                 qre_subcon = $5,
                 qre_nonlabor = $6,
                 modified_by = $7,
                 modified_datetime = now()
             WHERE project_fiscal_rid = $8`,
            [adjustment, netQre, qreFinalCost, qreFteCost, qreSubconCost,
             qreNonlaborCost, SYSTEM_USER_RID, projectFiscalRid]
          );
        }
      }
    }

    // 6d. Audit timeline entry -- matches createAccountTimelineEntry's
    // "project" branch (insertProjectTimeLine). rid/r_number/
    // created_datetime/event_datetime all use the table's own DB defaults,
    // exactly as the app's insert does (it never sets them either).
    await orgClient.query(
      `INSERT INTO "${schemaName}".project_timeline (
         created_by, event_type_rid, event_name, descriptions,
         account_rid, entity_name, entity_rid, created_by_name, project_rid
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
      [
        SYSTEM_USER_RID,
        eventTypeRid || null,
        'adjusted', // eventNames.ADJUST
        `for ${projectFiscal.project_code}`,
        accountRid,
        'QRE Percent', // entityTypes.QRE_PERCENT
        projectFiscalRid,
        createdByName || null,
        projectFiscalRid,
      ]
    );

    // 6e. QRE adjustment history row -- matches
    // schemaService.ts:insertQreAdjustmentHistory (a Sequelize model
    // .create() in the app). Stores the DELTA (rd_percent_adjustment),
    // matching the app's field naming, not the final percentage.
    //
    // rid is generated explicitly here rather than left to a column
    // DEFAULT: the model's `rid` default (models/projectQreAdjustmentHistory.ts)
    // is a Sequelize.literal applied client-side when the app calls
    // .create() -- it is not necessarily a real Postgres DEFAULT on this
    // table. Observed in practice: this tenant schema's
    // project_qre_adjustment_history.rid has no DB-level default, so a raw
    // INSERT that omits it violates NOT NULL. Generating it the same way
    // the ORM would ('<prefix>' || gen_random_uuid()) reproduces an
    // identical row regardless of whether the DB-level default exists.
    await orgClient.query(
      `INSERT INTO "${schemaName}".project_qre_adjustment_history (
         rid, project_fiscal_rid, account_rid, rd_percent_adjustment, comment, created_by, created_datetime
       ) VALUES ($1::text || gen_random_uuid(), $2, $3, $4, $5, $6, now())`,
      [RID_PREFIX, projectFiscalRid, accountRid, adjustment, record.comments || null, SYSTEM_USER_RID]
    );

    await orgClient.query('COMMIT');
    console.log('[org-db] transaction committed.');
  } catch (err) {
    await orgClient.query('ROLLBACK');
    throw err;
  }

  // ===========================================================================
  // Step 7: Main DB write, its own transaction.
  // Mirrors rawQueries.updateProjectFiscalSummaryQre. This statement is
  // idempotent (same WHERE key, same computed values), so if this step
  // fails after the Org DB step above already committed, it is safe to
  // re-run just this record.
  // ===========================================================================
  await mainClient.query('BEGIN');
  try {
    const pfsBackupRes = await mainClient.query(
      `INSERT INTO ${mainBackupTable} (run_id, table_name, row_rid, row_data)
       SELECT $1, $2, t.rid, to_jsonb(t)
       FROM ${MAIN_SCHEMA_NAME}.project_fiscal_summary t
       WHERE t.project_fiscal_rid = $3`,
      [runId, 'project_fiscal_summary', projectFiscalRid]
    );
    trackBackup(backupState, 'main', MAIN_SCHEMA_NAME, 'project_fiscal_summary', pfsBackupRes.rowCount);
    await mainClient.query(
      `UPDATE ${MAIN_SCHEMA_NAME}.project_fiscal_summary
       SET rd_percent_adjustment = $1,
           rd_percent_final = $2,
           qre_final = $3,
           qre_fte = $4,
           qre_subcon = $5,
           qre_nonlabor = $6,
           modified_by = $7,
           modified_datetime = now(),
           is_qualified = $8
       WHERE project_fiscal_rid = $9`,
      [adjustment, netQre, qreFinalCost, qreFteCost, qreSubconCost,
       qreNonlaborCost, SYSTEM_USER_RID, isQualified, projectFiscalRid]
    );
    await mainClient.query('COMMIT');
    console.log('[main-db] transaction committed.');
  } catch (err) {
    await mainClient.query('ROLLBACK');
    throw err;
  }

  return { projectFiscalRid };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const records = args.csv
    ? loadRecordsFromCsv(args.csv)
    : [{
        accountId: args.accountId,
        projectCode: args.projectCode,
        fiscalYear: args.fiscalYear,
        rdPercentPotentialAi: args.rdPercentPotentialAi,
        rdPercentAdjustment: args.rdPercentAdjustment,
        rdPercentFinal: args.rdPercentFinal,
        comments: args.comments,
      }];

  if (records.length === 0) {
    throw new Error('No data rows found in CSV.');
  }

  const { mainPort, orgPort, closeTunnels } = await openTunnels();

  const mainClient = new Client(mainClientConfig(mainPort));
  const orgClient = new Client(orgClientConfig(orgPort));
  await mainClient.connect();
  await orgClient.connect();

  // One run_id ties together every backup row this invocation writes, across
  // however many tenant schemas and records it touches -- this is what you
  // pass to rollback.js to undo the whole run. Not generated (or needed) on
  // a --dry-run pass, since dry runs never write anything, backups included.
  const runId = args.dryRun
    ? null
    : `run-${new Date().toISOString().replace(/[:.]/g, '-')}-${crypto.randomBytes(3).toString('hex')}`;
  if (runId) {
    console.log(`\nBackup run_id for this invocation: ${runId}`);
    console.log(`To roll back everything this run writes, run:`);
    console.log(`  node rollback.js --run-id ${runId}\n`);
  }
  const backupState = { orgSchemasEnsured: new Set(), mainEnsured: false, counts: {} };

  const results = [];
  try {
    for (const [idx, record] of records.entries()) {
      console.log(`\n=== Record ${idx + 1}/${records.length} ` +
        `(account_id=${record.accountId}, project_code=${record.projectCode}, fiscal_year=${record.fiscalYear}) ===`);
      try {
        const outcome = await processRecord(mainClient, orgClient, record, { dryRun: args.dryRun, runId, backupState });
        results.push({
          record, status: 'success', dryRun: !!args.dryRun, runId,
          resolvedProjectFiscalRid: outcome && outcome.projectFiscalRid,
        });
      } catch (err) {
        console.error(`[record failed] ${err.message}`);
        results.push({ record, status: 'failed', error: err.message, dryRun: !!args.dryRun, runId });
      }
    }
  } finally {
    await mainClient.end();
    await orgClient.end();
    await closeTunnels();
  }

  const succeeded = results.filter((r) => r.status === 'success').length;
  const failed = results.length - succeeded;
  console.log(`\n=== Summary: ${succeeded} succeeded, ${failed} failed, ${results.length} total ===`);

  // Output CSV is always written -- one row per input record, status column
  // is exactly 'success' or 'failed', error column carries the raised
  // message when a record fails.
  const outPath = writeResultsCsv(args.csv, results);
  console.log(`Results written to: ${outPath}`);

  // Backup manifest -- lists every schema/table this run's snapshots landed
  // in, so you have a concrete list to clean up once you're confident the
  // update is correct and no longer need rollback capability for this run.
  if (runId && Object.keys(backupState.counts).length > 0) {
    const manifestPath = writeBackupManifestCsv(args.csv, runId, backupState);
    console.log(`Backup manifest written to: ${manifestPath}`);
    console.log(`When you're done and no longer need these backups:`);
    console.log(`  node cleanup-backups.js --run-id ${runId} --yes        # delete just this run's backup rows`);
    console.log(`  node cleanup-backups.js --drop-tables --yes            # or drop the backup tables entirely (all runs)`);
  }

  if (failed > 0) {
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exitCode = 1;
});

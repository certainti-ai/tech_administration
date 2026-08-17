#!/usr/bin/env node
'use strict';

/**
 * Rollback tool for index.js (manual R&D percent update).
 *
 * Undoes an entire run of index.js by restoring every row it modified back
 * to its pre-update state, using the snapshots index.js wrote into each
 * touched schema's `manual_rd_percent_backup` table before every UPDATE
 * (see the "Backups" section in index.js's header comment).
 *
 * A run can span multiple Org DB tenant schemas (a CSV batch may cover
 * several accounts) plus the Main DB. This script does not require a
 * manifest of which schemas were touched -- it discovers them by scanning
 * every schema that has a `manual_rd_percent_backup` table for rows tagged
 * with the given run_id.
 *
 * If the SAME row was updated more than once within one run (e.g. two CSV
 * rows referencing the same project_fiscal_rid), there are multiple
 * snapshots for that row under the same run_id -- restoring uses the
 * EARLIEST one (lowest id), i.e. the true pre-run state, not an
 * intermediate one.
 *
 * Restoring writes every column from the JSONB snapshot back onto the live
 * row (except the row's own `rid`, which is only the match key). Backup
 * rows themselves are never deleted by this script -- they stay as an
 * audit trail regardless of whether you roll back.
 *
 * ---------------------------------------------------------------------------
 * Usage:
 *   node rollback.js --run-id <run_id>              # preview only, no writes
 *   node rollback.js --run-id <run_id> --yes        # actually restore
 * ---------------------------------------------------------------------------
 */

const { Client } = require('pg');
const { MAIN_SCHEMA_NAME, BACKUP_TABLE_NAME, openTunnels, mainClientConfig, orgClientConfig } = require('./db-config');

// Column names come from our own to_jsonb(t) snapshots (real Postgres
// column names), never from user input -- but since they get interpolated
// as SQL identifiers when rebuilding the restore UPDATE, this allow-list
// check stays as a defense-in-depth guard against a malformed/tampered
// backup row.
const SAFE_IDENTIFIER = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

function parseArgs(argv) {
  const out = { yes: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--run-id': out.runId = argv[++i]; break;
      case '--yes': out.yes = true; break;
      default:
        throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!out.runId) {
    throw new Error('Missing required argument: --run-id <run_id>');
  }
  return out;
}

// Finds every schema (in the given client's database) that has a
// manual_rd_percent_backup table, so we don't have to know in advance which
// tenant schemas a run touched.
async function findSchemasWithBackupTable(client) {
  const { rows } = await client.query(
    `SELECT table_schema FROM information_schema.tables WHERE table_name = $1`,
    [BACKUP_TABLE_NAME]
  );
  return rows.map((r) => r.table_schema);
}

// For a given schema + run_id, returns one row per (table_name, row_rid)
// -- the EARLIEST snapshot (lowest id) for that row within this run, i.e.
// the true pre-run state even if the row was touched more than once.
async function fetchEarliestSnapshots(client, schemaIdent, runId) {
  const { rows } = await client.query(
    `SELECT DISTINCT ON (table_name, row_rid)
       table_name, row_rid, row_data, id
     FROM ${schemaIdent}.${BACKUP_TABLE_NAME}
     WHERE run_id = $1
     ORDER BY table_name, row_rid, id ASC`,
    [runId]
  );
  return rows;
}

// Builds and executes an UPDATE that writes every column from a JSONB
// snapshot back onto the live row matching rid = row_rid.
async function restoreRow(client, schemaIdent, tableName, rowRid, rowData) {
  if (!SAFE_IDENTIFIER.test(tableName)) {
    throw new Error(`Refusing to restore: unsafe table name "${tableName}" in backup data`);
  }
  const columns = Object.keys(rowData).filter((c) => c !== 'rid');
  for (const c of columns) {
    if (!SAFE_IDENTIFIER.test(c)) {
      throw new Error(`Refusing to restore ${tableName}.${rowRid}: unsafe column name "${c}" in backup data`);
    }
  }
  if (columns.length === 0) return;

  const setClause = columns.map((c, i) => `"${c}" = $${i + 2}`).join(', ');
  const values = columns.map((c) => rowData[c]);
  await client.query(
    `UPDATE ${schemaIdent}.${tableName} SET ${setClause} WHERE rid = $1`,
    [rowRid, ...values]
  );
}

async function processDb(client, dbLabel, runId, yes) {
  const schemas = await findSchemasWithBackupTable(client);
  let totalRows = 0;
  const perTable = {};

  for (const schema of schemas) {
    const schemaIdent = `"${schema}"`;
    const snapshots = await fetchEarliestSnapshots(client, schemaIdent, runId);
    if (snapshots.length === 0) continue;

    console.log(`\n[${dbLabel}] schema ${schema}: ${snapshots.length} row(s) to restore`);
    for (const snap of snapshots) {
      perTable[snap.table_name] = (perTable[snap.table_name] || 0) + 1;
      console.log(`  - ${snap.table_name} rid=${snap.row_rid}`);
    }
    totalRows += snapshots.length;

    if (yes) {
      await client.query('BEGIN');
      try {
        for (const snap of snapshots) {
          await restoreRow(client, schemaIdent, snap.table_name, snap.row_rid, snap.row_data);
        }
        await client.query('COMMIT');
        console.log(`[${dbLabel}] schema ${schema}: restored, transaction committed.`);
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      }
    }
  }

  return { totalRows, perTable };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const { mainPort, orgPort, closeTunnels } = await openTunnels();

  const mainClient = new Client(mainClientConfig(mainPort));
  const orgClient = new Client(orgClientConfig(orgPort));
  await mainClient.connect();
  await orgClient.connect();

  try {
    if (!args.yes) {
      console.log(`Preview only (pass --yes to actually restore). run_id=${args.runId}`);
    } else {
      console.log(`Restoring run_id=${args.runId} ...`);
    }

    const orgResult = await processDb(orgClient, 'org-db', args.runId, args.yes);
    const mainResult = await processDb(mainClient, 'main-db', args.runId, args.yes);

    const totalRows = orgResult.totalRows + mainResult.totalRows;
    if (totalRows === 0) {
      console.log(`\nNo backup rows found for run_id=${args.runId}. Nothing to do.`);
      return;
    }

    console.log(`\n=== ${args.yes ? 'Restored' : 'Would restore'} ${totalRows} row(s) total ===`);
    const combined = { ...orgResult.perTable };
    for (const [k, v] of Object.entries(mainResult.perTable)) {
      combined[k] = (combined[k] || 0) + v;
    }
    for (const [table, count] of Object.entries(combined)) {
      console.log(`  ${table}: ${count}`);
    }

    if (!args.yes) {
      console.log(`\nRe-run with --yes to actually restore these rows.`);
    } else {
      console.log(`\nDone. Backup rows for this run_id were left in place (audit trail) -- not deleted.`);
    }
  } finally {
    await mainClient.end();
    await orgClient.end();
    await closeTunnels();
  }
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exitCode = 1;
});

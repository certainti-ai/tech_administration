#!/usr/bin/env node
'use strict';

/**
 * Cleanup tool for the `manual_rd_percent_backup` snapshot tables that
 * index.js creates. Use this once you've confirmed a run's updates are
 * correct and no longer need rollback capability for it.
 *
 * Two modes -- pick one:
 *
 *   --run-id <run_id>
 *     Deletes only the backup ROWS tagged with that run_id, in every
 *     schema that has them. Leaves the manual_rd_percent_backup table
 *     itself (and any OTHER runs' rows in it) intact. Safe/granular.
 *
 *   --drop-tables
 *     Drops the ENTIRE manual_rd_percent_backup table -- every run's
 *     history, in every schema that has one, both Org DB and Main DB.
 *     Only do this once you are fully done with this tool and have no
 *     need to roll back ANY past run.
 *
 * Both modes default to a preview (lists what would be removed, no writes).
 * Pass --yes to actually execute.
 *
 * ---------------------------------------------------------------------------
 * Usage:
 *   node cleanup-backups.js --run-id <run_id>              # preview
 *   node cleanup-backups.js --run-id <run_id> --yes        # delete this run's rows
 *   node cleanup-backups.js --drop-tables                  # preview
 *   node cleanup-backups.js --drop-tables --yes            # drop tables everywhere
 * ---------------------------------------------------------------------------
 */

const { Client } = require('pg');
const { BACKUP_TABLE_NAME, openTunnels, mainClientConfig, orgClientConfig } = require('./db-config');

function parseArgs(argv) {
  const out = { yes: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--run-id': out.runId = argv[++i]; break;
      case '--drop-tables': out.dropTables = true; break;
      case '--yes': out.yes = true; break;
      default:
        throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!out.runId && !out.dropTables) {
    throw new Error(
      "Pass either --run-id <run_id> (delete just that run's backup rows) " +
      'or --drop-tables (drop the whole backup table everywhere, all runs).'
    );
  }
  if (out.runId && out.dropTables) {
    throw new Error('Pass only one of --run-id or --drop-tables, not both.');
  }
  return out;
}

async function findSchemasWithBackupTable(client) {
  const { rows } = await client.query(
    `SELECT table_schema FROM information_schema.tables WHERE table_name = $1`,
    [BACKUP_TABLE_NAME]
  );
  return rows.map((r) => r.table_schema);
}

async function cleanupByRunId(client, dbLabel, runId, yes) {
  const schemas = await findSchemasWithBackupTable(client);
  let total = 0;
  for (const schema of schemas) {
    const schemaIdent = `"${schema}"`;
    const { rows } = await client.query(
      `SELECT COUNT(*)::int AS cnt FROM ${schemaIdent}.${BACKUP_TABLE_NAME} WHERE run_id = $1`,
      [runId]
    );
    const cnt = rows[0].cnt;
    if (cnt === 0) continue;
    console.log(`[${dbLabel}] schema ${schema}: ${cnt} backup row(s) for run_id=${runId}`);
    total += cnt;
    if (yes) {
      await client.query(`DELETE FROM ${schemaIdent}.${BACKUP_TABLE_NAME} WHERE run_id = $1`, [runId]);
      console.log(`[${dbLabel}] schema ${schema}: deleted.`);
    }
  }
  return total;
}

async function dropTablesEverywhere(client, dbLabel, yes) {
  const schemas = await findSchemasWithBackupTable(client);
  for (const schema of schemas) {
    const schemaIdent = `"${schema}"`;
    const { rows } = await client.query(
      `SELECT COUNT(*)::int AS cnt, COUNT(DISTINCT run_id)::int AS run_count
       FROM ${schemaIdent}.${BACKUP_TABLE_NAME}`
    );
    console.log(
      `[${dbLabel}] schema ${schema}: table has ${rows[0].cnt} row(s) across ${rows[0].run_count} run(s)`
    );
    if (yes) {
      await client.query(`DROP TABLE ${schemaIdent}.${BACKUP_TABLE_NAME}`);
      console.log(`[${dbLabel}] schema ${schema}: table dropped.`);
    }
  }
  return schemas.length;
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
      console.log('Preview only (pass --yes to actually execute).');
    }

    if (args.runId) {
      const orgTotal = await cleanupByRunId(orgClient, 'org-db', args.runId, args.yes);
      const mainTotal = await cleanupByRunId(mainClient, 'main-db', args.runId, args.yes);
      const total = orgTotal + mainTotal;
      if (total === 0) {
        console.log(`\nNo backup rows found for run_id=${args.runId}.`);
      } else {
        console.log(
          `\n=== ${args.yes ? 'Deleted' : 'Would delete'} ${total} backup row(s) for run_id=${args.runId} ===`
        );
      }
    } else {
      console.log('\nWARNING: --drop-tables removes ALL backup history for ALL runs, not just one.');
      const orgCount = await dropTablesEverywhere(orgClient, 'org-db', args.yes);
      const mainCount = await dropTablesEverywhere(mainClient, 'main-db', args.yes);
      const total = orgCount + mainCount;
      if (total === 0) {
        console.log('\nNo manual_rd_percent_backup tables found anywhere.');
      } else {
        console.log(
          `\n=== ${args.yes ? 'Dropped' : 'Would drop'} manual_rd_percent_backup in ${total} schema(s) ===`
        );
      }
    }

    if (!args.yes) {
      console.log('\nRe-run with --yes to actually execute.');
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

'use strict';

/**
 * Shared connection config and platform constants for index.js and
 * rollback.js. Kept in one file so there is a single place to edit
 * connection details (per the "no .env file" request) instead of two
 * copies drifting apart.
 *
 * WARNING: once you fill in real host/user/password values, this file
 * contains live credentials. Do not commit it in that state -- either
 * revert the credentials before committing, or add this file to your local
 * (untracked) git excludes, e.g.:
 *   git update-index --skip-worktree scripts/manual-rd-percent-update/db-config.js
 * or add a personal entry to .git/info/exclude.
 */

const { createTunnel } = require('tunnel-ssh');

const DB_CONFIG = {
  main: {
    host: 'prod-thinkrd365-psqlserver-centralus-pvt-main.postgres.database.azure.com',
    port: 5432,
    database: 'thinkrd365_pvt_main',
    user: 'adminUser',
    password: 'CHANGE_ME',
    ssl: true, // set false for a local/dev Postgres without TLS
  },
  org: {
    host: 'prod-thinkrd365-psqlserver-centralus-pvt-org.postgres.database.azure.com',
    port: 5432,
    database: 'thinkrd365_pvt_org',
    user: 'adminUser',
    password: 'CHANGE_ME',
    ssl: true,
  },
};

// SSH bastion/jump-host used to reach both DB servers.
const SSH_CONFIG = {
  host: '172.203.151.166',
  port: 22,
  username: 'thinkrd_DevOps',
  password: 'CHANGE_ME',
};

const MAIN_SCHEMA_NAME = 'trd365';
const SCHEMANAME_PREFIX = 'trd365_';

// Matches ENV_PREFIX in each module's src/utils/constant(s).ts
// (process.env.NODE_ENV_DB_PREFIX || 'D001-'). These standalone scripts have
// no access to that runtime env var, so it's a plain constant here --
// change it if your environment uses a different RID prefix.
const RID_PREFIX = 'D001-';

// Name of the pre-update row-snapshot table index.js creates (if missing)
// in every Org DB tenant schema it touches, and in the Main DB `trd365`
// schema. rollback.js reads from these same tables to undo a run.
const BACKUP_TABLE_NAME = 'manual_rd_percent_backup';

function assertConfigured(cfg, label) {
  const unset = Object.entries(cfg)
    .filter(([k, v]) => k !== 'ssl' && (v === 'CHANGE_ME' || v === undefined || v === ''))
    .map(([k]) => k);
  if (unset.length) {
    throw new Error(
      `DB_CONFIG.${label} is missing: ${unset.join(', ')}. Edit the DB_CONFIG block at the ` +
      `top of db-config.js with real connection details before running.`
    );
  }
}

// Opens SSH tunnels for both the Main DB and Org DB, then returns the local
// port for each along with a closeTunnels() function to shut both down when
// done. Call this once at the top of main() and pass the ports into
// mainClientConfig / orgClientConfig.
async function openTunnels() {
  assertConfigured(DB_CONFIG.main, 'main');
  assertConfigured(DB_CONFIG.org, 'org');

  const sshOptions = {
    host: SSH_CONFIG.host,
    port: SSH_CONFIG.port,
    username: SSH_CONFIG.username,
    password: SSH_CONFIG.password,
  };

  console.log(`[tunnel] Opening SSH tunnels via ${SSH_CONFIG.host}:${SSH_CONFIG.port} ...`);

  const [mainServer, mainSshClient] = await createTunnel(
    { autoClose: false },
    { host: '127.0.0.1', port: 0 },
    sshOptions,
    { srcAddr: '127.0.0.1', srcPort: 0, dstAddr: DB_CONFIG.main.host, dstPort: DB_CONFIG.main.port }
  );
  const mainPort = mainServer.address().port;
  console.log(`[tunnel] main-db: 127.0.0.1:${mainPort} -> ${DB_CONFIG.main.host}:${DB_CONFIG.main.port}`);

  const [orgServer, orgSshClient] = await createTunnel(
    { autoClose: false },
    { host: '127.0.0.1', port: 0 },
    sshOptions,
    { srcAddr: '127.0.0.1', srcPort: 0, dstAddr: DB_CONFIG.org.host, dstPort: DB_CONFIG.org.port }
  );
  const orgPort = orgServer.address().port;
  console.log(`[tunnel] org-db:  127.0.0.1:${orgPort} -> ${DB_CONFIG.org.host}:${DB_CONFIG.org.port}`);

  async function closeTunnels() {
    await new Promise((resolve) => mainServer.close(resolve));
    mainSshClient.end();
    await new Promise((resolve) => orgServer.close(resolve));
    orgSshClient.end();
    console.log('[tunnel] SSH tunnels closed.');
  }

  return { mainPort, orgPort, closeTunnels };
}

// localPort: the tunnel's local port returned by openTunnels(). When set,
// the pg client connects to 127.0.0.1:<localPort> instead of the remote host.
function mainClientConfig(localPort) {
  assertConfigured(DB_CONFIG.main, 'main');
  return {
    host: localPort ? '127.0.0.1' : DB_CONFIG.main.host,
    port: localPort ? localPort : Number(DB_CONFIG.main.port || 5432),
    database: DB_CONFIG.main.database,
    user: DB_CONFIG.main.user,
    password: DB_CONFIG.main.password,
    ssl: DB_CONFIG.main.ssl ? { rejectUnauthorized: false } : false,
  };
}

function orgClientConfig(localPort) {
  assertConfigured(DB_CONFIG.org, 'org');
  return {
    host: localPort ? '127.0.0.1' : DB_CONFIG.org.host,
    port: localPort ? localPort : Number(DB_CONFIG.org.port || 5432),
    database: DB_CONFIG.org.database,
    user: DB_CONFIG.org.user,
    password: DB_CONFIG.org.password,
    ssl: DB_CONFIG.org.ssl ? { rejectUnauthorized: false } : false,
  };
}

module.exports = {
  DB_CONFIG,
  SSH_CONFIG,
  MAIN_SCHEMA_NAME,
  SCHEMANAME_PREFIX,
  RID_PREFIX,
  BACKUP_TABLE_NAME,
  openTunnels,
  mainClientConfig,
  orgClientConfig,
};

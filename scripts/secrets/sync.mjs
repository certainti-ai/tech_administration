import { createHash } from "node:crypto";

/**
 * Transfer logic between the process environment and a Key Vault.
 *
 * Everything here is pure or takes the vault client as an argument, so the
 * whole flow can be tested against an in-memory fake without an Azure account.
 * No function in this module prints or returns a secret value in a log-shaped
 * form — callers get values only through the explicit render functions.
 */

/** Short, salt-free digest used to compare values without revealing them. */
export function digest(value) {
  return createHash("sha256").update(value, "utf8").digest("hex").slice(0, 12);
}

/**
 * Decide what a push would do, without doing it.
 *
 * Entries absent from the environment are reported rather than written as empty
 * strings — an empty secret in a vault is worse than a missing one, because
 * consumers treat it as present and fail somewhere further away.
 */
export function planPush(selected, env) {
  const writes = [];
  const missing = [];

  for (const entry of selected) {
    const value = env[entry.env];
    if (value === undefined || value === "") {
      missing.push(entry);
      continue;
    }
    writes.push({ entry, value, digest: digest(value) });
  }

  return { writes, missing };
}

/** Execute a push plan. `onResult` receives per-entry outcomes for reporting. */
export async function applyPush(client, plan, { onResult = () => {} } = {}) {
  const applied = [];
  const failed = [];

  for (const write of plan.writes) {
    try {
      await client.setSecret(write.entry.secret, write.value);
      applied.push(write.entry);
      onResult({ entry: write.entry, status: "written", digest: write.digest });
    } catch (error) {
      failed.push({ entry: write.entry, error });
      onResult({ entry: write.entry, status: "failed", error });
    }
  }

  return { applied, failed };
}

/**
 * Read every selected entry from the vault.
 *
 * A missing secret is recorded rather than thrown, so one absent entry does not
 * hide the state of the other thirty.
 */
export async function fetchAll(client, selected) {
  const values = new Map();
  const missing = [];

  for (const entry of selected) {
    try {
      const secret = await client.getSecret(entry.secret);
      const value = secret?.value;
      if (value === undefined || value === "") {
        missing.push(entry);
      } else {
        values.set(entry.env, value);
      }
    } catch (error) {
      if (isNotFound(error)) {
        missing.push(entry);
      } else {
        throw error;
      }
    }
  }

  return { values, missing };
}

function isNotFound(error) {
  return error?.statusCode === 404 || error?.code === "SecretNotFound";
}

/**
 * Compare the vault against the current environment by digest.
 *
 * Reports where they agree, differ, or are absent on one side — without
 * exposing either value.
 */
export async function compareWithEnv(client, selected, env) {
  const { values, missing } = await fetchAll(client, selected);
  const rows = [];

  for (const entry of selected) {
    const vaultValue = values.get(entry.env);
    const envValue = env[entry.env];
    const inVault = vaultValue !== undefined;
    const inEnv = envValue !== undefined && envValue !== "";

    let status;
    if (!inVault && !inEnv) status = "absent-both";
    else if (!inVault) status = "vault-missing";
    else if (!inEnv) status = "env-missing";
    else status = vaultValue === envValue ? "match" : "differ";

    rows.push({
      entry,
      status,
      vaultDigest: inVault ? digest(vaultValue) : null,
      envDigest: inEnv ? digest(envValue) : null,
    });
  }

  return { rows, missing };
}

// ------------------------------------------------------------------ renderers

/** Quote a value for a POSIX shell: single quotes, with embedded quotes closed. */
export function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

export function renderShell(values) {
  return [...values.entries()]
    .map(([name, value]) => `export ${name}=${shellQuote(value)}`)
    .join("\n");
}

/** Quote a value for dotenv format, escaping what would otherwise break a line. */
export function dotenvQuote(value) {
  const escaped = String(value)
    .replaceAll("\\", "\\\\")
    .replaceAll('"', '\\"')
    .replaceAll("\n", "\\n")
    .replaceAll("\r", "\\r");
  return `"${escaped}"`;
}

export function renderDotenv(values) {
  return [...values.entries()]
    .map(([name, value]) => `${name}=${dotenvQuote(value)}`)
    .join("\n");
}

export function renderJson(values) {
  return JSON.stringify(Object.fromEntries(values), null, 2);
}

export const RENDERERS = {
  shell: renderShell,
  env: renderDotenv,
  json: renderJson,
};

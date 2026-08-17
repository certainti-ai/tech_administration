#!/usr/bin/env node
/**
 * Verify the vault against the manifest, and optionally against this
 * environment. Prints digests, never values — safe to run in CI logs.
 *
 *   node scripts/secrets/check.mjs --vault certainti-kv
 *
 * Statuses:
 *   match          vault and environment hold the same value
 *   differ         both present, values disagree (migration drift)
 *   env-missing    in the vault only — expected once local copies are removed
 *   vault-missing  in the environment only — not migrated yet
 *   absent-both    neither has it
 */
import { selectEntries, validateManifest } from "./manifest.mjs";
import { compareWithEnv } from "./sync.mjs";
import { createVaultClient, explainAuthFailure, resolveVaultName } from "./client.mjs";
import { asList, fail, pad, parseArgs } from "./cli.mjs";

const { flags } = parseArgs(process.argv.slice(2));

if (flags.help) {
  console.log(
    [
      "Usage: node scripts/secrets/check.mjs [options]",
      "",
      "  --vault <name>      Key Vault name (or set AZURE_KEY_VAULT_NAME)",
      "  --group <id>        Limit to one or more groups (repeatable)",
      "  --require-complete  Exit non-zero if any secret is missing from the vault",
    ].join("\n"),
  );
  process.exit(0);
}

const problems = validateManifest();
if (problems.length > 0) {
  fail(`Manifest is invalid:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.log(`Manifest OK: ${selectEntries({ includeBootstrap: true }).length} entries defined.\n`);

const selected = selectEntries({ groupIds: asList(flags.group) });

let client;
try {
  client = createVaultClient(resolveVaultName(flags.vault));
} catch (error) {
  fail(explainAuthFailure(error));
  process.exit(1);
}

let comparison;
try {
  comparison = await compareWithEnv(client, selected, process.env);
} catch (error) {
  fail(explainAuthFailure(error));
  process.exit(1);
}

console.log(`${pad("VAULT SECRET", 26)}${pad("STATUS", 16)}${pad("VAULT", 14)}ENV`);
for (const row of comparison.rows) {
  console.log(
    pad(row.entry.secret, 26) +
      pad(row.status, 16) +
      pad(row.vaultDigest ?? "-", 14) +
      (row.envDigest ?? "-"),
  );
}

const tally = comparison.rows.reduce((counts, row) => {
  counts[row.status] = (counts[row.status] ?? 0) + 1;
  return counts;
}, {});

console.log(
  `\n${Object.entries(tally)
    .map(([status, count]) => `${status}: ${count}`)
    .join("   ")}`,
);

const differing = comparison.rows.filter((row) => row.status === "differ");
if (differing.length > 0) {
  fail(
    `\n${differing.length} secret(s) differ between the vault and this environment. ` +
      "Re-run push.mjs --apply, or reconcile by hand.",
  );
}

if (flags["require-complete"] === true) {
  const absent = comparison.rows.filter((row) => row.status === "vault-missing" || row.status === "absent-both");
  if (absent.length > 0) {
    fail(`${absent.length} secret(s) are not in the vault.`);
  }
}

#!/usr/bin/env node
/**
 * One-time migration: copy secrets from the current environment into Key Vault.
 *
 * Dry run by default — it prints exactly what it would write and stops. Pass
 * `--apply` to perform the writes.
 *
 *   node scripts/secrets/push.mjs --vault certainti-kv
 *   node scripts/secrets/push.mjs --vault certainti-kv --apply
 *
 * Values are never printed. Each row shows a short digest so you can confirm a
 * value matches what you expect without it appearing on screen or in CI logs.
 */
import { selectEntries, validateManifest } from "./manifest.mjs";
import { planPush, applyPush } from "./sync.mjs";
import { createVaultClient, explainAuthFailure, resolveVaultName } from "./client.mjs";
import { asList, fail, pad, parseArgs } from "./cli.mjs";

const { flags } = parseArgs(process.argv.slice(2));

if (flags.help) {
  console.log(
    [
      "Usage: node scripts/secrets/push.mjs [options]",
      "",
      "  --vault <name>         Key Vault name (or set AZURE_KEY_VAULT_NAME)",
      "  --apply                Perform the writes (default is a dry run)",
      "  --group <id>           Limit to one or more groups (repeatable, comma-separated)",
      "  --include-bootstrap    Also push the Azure service principal (see below)",
      "",
      "The service principal that unlocks the vault is excluded by default:",
      "storing it inside the vault it authenticates to is circular.",
    ].join("\n"),
  );
  process.exit(0);
}

const problems = validateManifest();
if (problems.length > 0) {
  fail(`Manifest is invalid:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}

const includeBootstrap = flags["include-bootstrap"] === true;
const selected = selectEntries({
  includeBootstrap,
  groupIds: asList(flags.group),
});

if (selected.length === 0) {
  fail("No entries selected. Check --group against the manifest.");
  process.exit(1);
}

const plan = planPush(selected, process.env);
const apply = flags.apply === true;

console.log(
  `${apply ? "Pushing" : "Dry run —"} ${plan.writes.length} secret(s)` +
    `${apply ? "" : " would be written"}; ${plan.missing.length} not set locally.\n`,
);

console.log(`${pad("ENVIRONMENT", 26)}${pad("VAULT SECRET", 26)}DIGEST`);
for (const write of plan.writes) {
  console.log(
    `${pad(write.entry.env, 26)}${pad(write.entry.secret, 26)}${write.digest}`,
  );
}

if (plan.missing.length > 0) {
  console.log("\nNot set in this environment (skipped, not written as empty):");
  for (const entry of plan.missing) {
    console.log(`  ${entry.env}`);
  }
}

if (!includeBootstrap) {
  console.log(
    "\nExcluded: the Azure service principal (ARM_*). It authenticates to this" +
      "\nvault, so it cannot live inside it. Use --include-bootstrap to override.",
  );
}

if (!apply) {
  console.log("\nNothing written. Re-run with --apply to perform the writes.");
  process.exit(0);
}

let client;
try {
  client = createVaultClient(resolveVaultName(flags.vault));
} catch (error) {
  fail(explainAuthFailure(error));
  process.exit(1);
}

console.log("");
const { applied, failed } = await applyPush(client, plan, {
  onResult: ({ entry, status, error }) => {
    if (status === "written") {
      console.log(`  ok      ${entry.secret}`);
    } else {
      console.log(`  FAILED  ${entry.secret}: ${error?.message ?? error}`);
    }
  },
});

console.log(`\nWrote ${applied.length} secret(s).`);

if (failed.length > 0) {
  fail(`${failed.length} failed. First error:\n${explainAuthFailure(failed[0].error)}`);
}

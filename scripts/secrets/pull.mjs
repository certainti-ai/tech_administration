#!/usr/bin/env node
/**
 * Fetch secrets from Key Vault and emit them for the current context.
 *
 *   eval "$(node scripts/secrets/pull.mjs --format shell)"   # load into a shell
 *   node scripts/secrets/pull.mjs --format env --out .env.local
 *   node scripts/secrets/pull.mjs --format json               # for a wrapper process
 *
 * Writing to a path inside the repo that git does not ignore is refused: a
 * stray `.env` is one `git add -A` away from being published.
 */
import { writeFileSync } from "node:fs";
import { selectEntries, validateManifest } from "./manifest.mjs";
import { RENDERERS, fetchAll } from "./sync.mjs";
import { createVaultClient, explainAuthFailure, resolveVaultName } from "./client.mjs";
import { asList, assertSafeOutputPath, fail, parseArgs } from "./cli.mjs";

const { flags } = parseArgs(process.argv.slice(2));

if (flags.help) {
  console.log(
    [
      "Usage: node scripts/secrets/pull.mjs [options]",
      "",
      "  --vault <name>       Key Vault name (or set AZURE_KEY_VAULT_NAME)",
      "  --format <fmt>       shell | env | json   (default: shell)",
      "  --out <path>         Write to a file instead of stdout",
      "  --group <id>         Limit to one or more groups (repeatable)",
      "  --allow-missing      Exit 0 even when some secrets are absent",
    ].join("\n"),
  );
  process.exit(0);
}

const problems = validateManifest();
if (problems.length > 0) {
  fail(`Manifest is invalid:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}

const format = flags.format === true || flags.format === undefined ? "shell" : flags.format;
const render = RENDERERS[format];
if (!render) {
  fail(`Unknown --format "${format}". Expected one of: ${Object.keys(RENDERERS).join(", ")}.`);
  process.exit(1);
}

// Bootstrap credentials are never fetched: whatever is running this already
// used them to authenticate, so re-emitting them only widens their exposure.
const selected = selectEntries({ groupIds: asList(flags.group) });

let outPath = null;
if (typeof flags.out === "string") {
  try {
    outPath = assertSafeOutputPath(flags.out);
  } catch (error) {
    fail(error.message);
    process.exit(1);
  }
}

let client;
try {
  client = createVaultClient(resolveVaultName(flags.vault));
} catch (error) {
  fail(explainAuthFailure(error));
  process.exit(1);
}

let result;
try {
  result = await fetchAll(client, selected);
} catch (error) {
  fail(explainAuthFailure(error));
  process.exit(1);
}

const output = render(result.values);

if (outPath) {
  writeFileSync(outPath, `${output}\n`, { mode: 0o600 });
  // Status goes to stderr so `--out` stays composable with a piped stdout.
  console.error(`Wrote ${result.values.size} secret(s) to ${outPath} (mode 0600).`);
} else {
  process.stdout.write(`${output}\n`);
}

if (result.missing.length > 0) {
  const names = result.missing.map((entry) => entry.secret).join(", ");
  console.error(`\nMissing from the vault (${result.missing.length}): ${names}`);
  if (flags["allow-missing"] !== true) {
    process.exitCode = 1;
  }
}

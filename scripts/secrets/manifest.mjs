import { assertValidVaultName, toVaultName } from "./naming.mjs";

/**
 * The inventory of secrets that live in Azure Key Vault.
 *
 * This file is the single source of truth. Every context — Claude Code
 * sessions, local shells, GitHub Actions, deployed services — reads the same
 * list, so a secret added here becomes available everywhere rather than being
 * re-entered per environment.
 *
 * Entry fields:
 *   env        exact environment variable name, preserving case
 *   secret     Key Vault secret name (defaults to the derived form)
 *   sensitive  true for values that grant access; false for connection details
 *   required   whether consumers should fail fast when it is absent
 */

/**
 * The service principal that unlocks the vault cannot itself live in the vault.
 *
 * Groups flagged `bootstrap` are excluded from `push` by default: storing
 * ARM_CLIENT_SECRET inside the Key Vault it authenticates to is circular, and
 * copying it around is what the OIDC/managed-identity path in docs/secrets.md
 * exists to eliminate. Each context should hold exactly one bootstrap
 * credential — or none, when federation is available.
 */
const GROUPS = [
  {
    id: "maindb",
    title: "Main application database",
    description: "Primary Postgres instance, reached through an SSH bastion.",
    entries: [
      { env: "MAINDB_HOST", sensitive: false },
      { env: "MAINDB_PORT", sensitive: false },
      { env: "MAINDB_USER", sensitive: false },
      { env: "MAINDB_PASSWORD", sensitive: true },
      { env: "MAINDB_DBNAME", sensitive: false },
      { env: "MAINDB_SSLMODE", sensitive: false },
      { env: "MAINDB_SSH_HOST", sensitive: false },
      { env: "MAINDB_SSH_PORT", sensitive: false },
      { env: "MAINDB_SSH_USER", sensitive: false },
      { env: "MAINDB_SSH_PASSWORD", sensitive: true },
    ],
  },
  {
    id: "orgdb",
    title: "Organisation database",
    description: "Secondary Postgres instance, reached through an SSH bastion.",
    entries: [
      { env: "ORGDB_HOST", sensitive: false },
      { env: "ORGDB_PORT", sensitive: false },
      { env: "ORGDB_USER", sensitive: false },
      { env: "ORGDB_PASSWORD", sensitive: true },
      { env: "ORGDB_DBNAME", sensitive: false },
      { env: "ORGDB_SSLMODE", sensitive: false },
      { env: "ORGDB_SSH_HOST", sensitive: false },
      { env: "ORGDB_SSH_PORT", sensitive: false },
      { env: "ORGDB_SSH_USER", sensitive: false },
      { env: "ORGDB_SSH_PASSWORD", sensitive: true },
    ],
  },
  {
    id: "trd365ai",
    title: "TRD365 AI database",
    description: "Direct Postgres connection; no bastion.",
    entries: [
      { env: "TRD365AI_HOST", sensitive: false },
      { env: "TRD365AI_PORT", sensitive: false },
      { env: "TRD365AI_USER", sensitive: false },
      { env: "TRD365AI_PASSWORD", sensitive: true },
      { env: "TRD365AI_DBNAME", sensitive: false },
      { env: "TRD365AI_SSLMODE", sensitive: false },
    ],
  },
  {
    id: "aws",
    title: "AWS access keys",
    description:
      "Long-lived IAM user keys. Prefer GitHub OIDC in CI and an instance role in deployed services; these exist for contexts that cannot federate.",
    entries: [
      { env: "AWS_ACCESS_KEY_ID", sensitive: false },
      { env: "AWS_SECRET_ACCESS_KEY", sensitive: true },
    ],
  },
  {
    id: "terraform",
    title: "Terraform inputs",
    description:
      "TF_VAR_ variables are matched case-sensitively by Terraform, so the exact name matters.",
    entries: [
      { env: "TF_VAR_repo_pat", secret: "tf-var-repo-pat", sensitive: true },
    ],
  },
  {
    id: "azure",
    title: "Azure service principal (bootstrap)",
    bootstrap: true,
    description:
      "Authenticates to Key Vault itself, so it cannot be stored inside it. Held per context as the single bootstrap credential, or replaced entirely by OIDC / managed identity.",
    entries: [
      { env: "ARM_CLIENT_ID", sensitive: false },
      { env: "ARM_TENANT_ID", sensitive: false },
      { env: "ARM_SUBSCRIPTION_ID", sensitive: false },
      { env: "ARM_CLIENT_SECRET", sensitive: true },
    ],
  },
];

/** Normalise a group's entries, filling in derived vault names. */
function buildEntries(group) {
  return group.entries.map((entry) => {
    const secret = assertValidVaultName(entry.secret ?? toVaultName(entry.env));
    return {
      env: entry.env,
      secret,
      sensitive: entry.sensitive ?? true,
      required: entry.required ?? true,
      group: group.id,
      bootstrap: group.bootstrap === true,
    };
  });
}

export const groups = GROUPS.map((group) => ({
  id: group.id,
  title: group.title,
  description: group.description,
  bootstrap: group.bootstrap === true,
  entries: buildEntries(group),
}));

/** Every entry across every group, flattened. */
export const entries = groups.flatMap((group) => group.entries);

/**
 * Entries eligible for the vault.
 *
 * Bootstrap credentials are excluded unless explicitly asked for, so the
 * circular case has to be a deliberate choice rather than a default.
 */
export function selectEntries({
  includeBootstrap = false,
  groupIds = null,
} = {}) {
  return entries.filter((entry) => {
    if (!includeBootstrap && entry.bootstrap) return false;
    if (groupIds && !groupIds.includes(entry.group)) return false;
    return true;
  });
}

export function findByEnv(envName) {
  return entries.find((entry) => entry.env === envName);
}

/**
 * Structural self-check. Run by the test suite and by `check.mjs` so a
 * malformed manifest is caught before anything touches a real vault.
 */
export function validateManifest() {
  const problems = [];
  const seenEnv = new Map();
  const seenSecret = new Map();

  for (const entry of entries) {
    if (seenEnv.has(entry.env)) {
      problems.push(`Duplicate environment name: ${entry.env}`);
    }
    seenEnv.set(entry.env, entry);

    const clash = seenSecret.get(entry.secret);
    if (clash) {
      problems.push(
        `Vault name "${entry.secret}" is claimed by both ${clash.env} and ${entry.env}`,
      );
    }
    seenSecret.set(entry.secret, entry);

    if (!isValidVaultNameSafe(entry.secret)) {
      problems.push(`Invalid vault name for ${entry.env}: "${entry.secret}"`);
    }
  }

  return problems;
}

function isValidVaultNameSafe(name) {
  try {
    assertValidVaultName(name);
    return true;
  } catch {
    return false;
  }
}

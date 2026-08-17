/**
 * Mapping between environment variable names and Azure Key Vault secret names.
 *
 * Key Vault permits only `[0-9a-zA-Z-]` in a secret name, so `MAINDB_PASSWORD`
 * cannot be stored verbatim. The obvious scheme — lowercase and swap `_` for
 * `-` — is *not* reliably reversible: `TF_VAR_repo_pat` would come back as
 * `TF_VAR_REPO_PAT`, and Terraform matches `TF_VAR_` variable names
 * case-sensitively, so the restored variable would be silently ignored.
 *
 * The manifest therefore carries the exact environment name for every entry and
 * treats the derived vault name as a default that an entry may override. These
 * helpers exist to compute and validate that default, never to reverse it.
 */

/** Key Vault's own constraint on secret names. */
const VAULT_NAME_PATTERN = /^[0-9a-zA-Z-]{1,127}$/;

const ENV_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Derive the conventional vault secret name for an environment variable. */
export function toVaultName(envName) {
  if (typeof envName !== "string" || !ENV_NAME_PATTERN.test(envName)) {
    throw new TypeError(`Not a valid environment variable name: "${envName}"`);
  }
  return envName.toLowerCase().replaceAll("_", "-");
}

export function isValidVaultName(name) {
  return typeof name === "string" && VAULT_NAME_PATTERN.test(name);
}

export function assertValidVaultName(name) {
  if (!isValidVaultName(name)) {
    throw new TypeError(
      `"${name}" is not a usable Key Vault secret name (allowed: letters, digits, hyphen; 1-127 chars)`,
    );
  }
  return name;
}

/**
 * Whether the derived name round-trips back to the original environment name.
 *
 * Used by the manifest's self-check to catch entries — like `TF_VAR_repo_pat` —
 * whose casing would be lost, so they are forced to be explicit rather than
 * quietly restored under the wrong name.
 */
export function roundTrips(envName) {
  return toVaultName(envName).replaceAll("-", "_").toUpperCase() === envName;
}

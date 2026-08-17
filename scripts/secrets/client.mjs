import { DefaultAzureCredential } from "@azure/identity";
import { SecretClient } from "@azure/keyvault-secrets";

/**
 * Key Vault client construction.
 *
 * `DefaultAzureCredential` is what lets one script serve every context without
 * branching: it tries environment credentials (the ARM_* service principal),
 * then workload identity, then managed identity, then the signed-in Azure CLI
 * user. So the same command works from a Claude Code session, a developer
 * laptop running `az login`, a GitHub Actions job authenticated over OIDC, and
 * a deployed service with a managed identity attached.
 */

/** Environment variable naming the target vault. */
export const VAULT_ENV = "AZURE_KEY_VAULT_NAME";

export function resolveVaultName(explicit, env = process.env) {
  const name = explicit ?? env[VAULT_ENV];
  if (!name) {
    throw new Error(
      `No Key Vault specified. Pass --vault <name> or set ${VAULT_ENV}.`,
    );
  }
  if (!/^[a-zA-Z0-9-]{3,24}$/.test(name)) {
    throw new Error(
      `"${name}" is not a valid Key Vault name (3-24 chars, letters/digits/hyphen).`,
    );
  }
  return name;
}

export function vaultUrl(vaultName) {
  return `https://${vaultName}.vault.azure.net`;
}

export function createVaultClient(vaultName, { credential } = {}) {
  return new SecretClient(
    vaultUrl(vaultName),
    credential ?? new DefaultAzureCredential(),
  );
}

/**
 * Turn an Azure auth failure into something a reader can act on. The SDK's own
 * message is a wall of chained credential errors that buries the cause.
 */
export function explainAuthFailure(error) {
  const message = String(error?.message ?? error);

  if (/CredentialUnavailableError|DefaultAzureCredential failed/i.test(message)) {
    return [
      "Could not authenticate to Azure. One of these needs to be true:",
      "  • ARM_CLIENT_ID / ARM_TENANT_ID / ARM_CLIENT_SECRET are set (service principal), or",
      "  • you are signed in with `az login` (local development), or",
      "  • the job authenticated over OIDC (GitHub Actions), or",
      "  • a managed identity is attached (deployed services).",
      "",
      `Underlying error: ${message}`,
    ].join("\n");
  }

  if (/Forbidden|403/.test(message)) {
    return [
      "Authenticated, but not authorised for this vault.",
      "The identity needs the 'Key Vault Secrets User' role to read, or",
      "'Key Vault Secrets Officer' to write, scoped to the vault.",
      "",
      `Underlying error: ${message}`,
    ].join("\n");
  }

  return message;
}

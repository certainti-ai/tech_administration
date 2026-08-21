import { ClientSecretCredential, DefaultAzureCredential } from "@azure/identity";
import { SecretClient } from "@azure/keyvault-secrets";

/**
 * Key Vault client construction.
 *
 * `DefaultAzureCredential` covers most contexts without branching: workload
 * identity, managed identity, a signed-in Azure CLI user, and its own
 * `EnvironmentCredential`. That is what lets one command serve a developer
 * laptop, a GitHub Actions job on OIDC, and a deployed service.
 *
 * It does **not** cover `ARM_*`. `EnvironmentCredential` reads `AZURE_CLIENT_ID`
 * / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET`; `ARM_*` is Terraform's naming and
 * the SDK ignores it entirely. This project's environment provides only `ARM_*`,
 * so relying on the default chain here fails with "EnvironmentCredential is
 * unavailable" while a perfectly good service principal sits in the environment
 * — which is exactly what happened on the first real push. So `ARM_*` is
 * honoured explicitly, and only then does the chain take over.
 */

/** Service-principal credential from `ARM_*`, or null if not fully configured. */
export function armCredential(env = process.env) {
  const tenant = env.ARM_TENANT_ID;
  const client = env.ARM_CLIENT_ID;
  const secret = env.ARM_CLIENT_SECRET;
  if (!tenant || !client || !secret) return null;
  return new ClientSecretCredential(tenant, client, secret);
}

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

export function createVaultClient(vaultName, { credential, env = process.env } = {}) {
  return new SecretClient(
    vaultUrl(vaultName),
    credential ?? armCredential(env) ?? new DefaultAzureCredential(),
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

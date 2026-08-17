# Secrets

One Azure Key Vault is the source of truth for every credential the
organisation's tooling needs. Each context — a Claude Code session, a developer
laptop, a GitHub Actions job, a deployed service — authenticates in its own way
and then reads the same secrets, so a value is entered once and never copied
between environments again.

```
                       ┌──────────────────────┐
                       │  Azure Key Vault     │   ← single source of truth
                       │  (33 secrets)        │
                       └──────────┬───────────┘
              ┌───────────────┬───┴────────┬──────────────────┐
              │               │            │                  │
      Claude Code       local shell   GitHub Actions    deployed service
      service principal  az login     OIDC federation   managed identity
```

The inventory lives in [`scripts/secrets/manifest.mjs`](../scripts/secrets/manifest.mjs).
Adding an entry there makes it available in all four contexts at once.

## Why not GitHub Actions secrets

Actions secrets solve a narrower problem: they are readable only by workflows in
the repository that holds them. They cannot be read by a local shell, a Claude
Code session, or a running service, and each repository needs its own copy. Key
Vault is reachable from all of them with per-identity access control and an
audit log, so it is the store; GitHub gets an OIDC federation and holds no
long-lived secret at all.

## One-time setup

### 1. Create the vault

```bash
az group create --name certainti-platform --location centralindia
az keyvault create \
  --name certainti-kv \
  --resource-group certainti-platform \
  --enable-rbac-authorization true
```

RBAC authorisation (rather than legacy access policies) is what lets the roles
below be assigned per identity.

### 2. Grant yourself write access

```bash
az role assignment create \
  --role "Key Vault Secrets Officer" \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --scope "$(az keyvault show --name certainti-kv --query id -o tsv)"
```

| Role | Grants | Give it to |
|---|---|---|
| Key Vault Secrets Officer | read + write | administrators, the migration run |
| Key Vault Secrets User | read only | CI, deployed services, day-to-day sessions |

Everything that only consumes secrets gets **Secrets User**. Write access is the
exception, not the default.

### 3. Migrate the current values

Run this from a machine that has the values in its environment *and* can reach
Azure. It prints a plan and writes nothing until `--apply` is passed:

```bash
export AZURE_KEY_VAULT_NAME=certainti-kv
node scripts/secrets/push.mjs                 # dry run — review this first
node scripts/secrets/push.mjs --apply
node scripts/secrets/check.mjs                # confirm vault matches environment
```

Secret values are never printed. Each row shows a 12-character digest so you can
confirm a value is what you expect without it appearing on screen or in a log.

### 4. Remove the copies

Once `check.mjs` reports `match` for every entry, delete the variables from the
Claude Code environment configuration and from any other place they were pasted.
Until that happens the vault is an additional copy rather than a replacement,
which makes the situation worse rather than better.

The one variable that stays behind is the bootstrap credential — see below.

## The bootstrap problem

Reading from Key Vault requires an identity, and that identity cannot itself be
stored in Key Vault. Every context therefore holds exactly one credential, or
none:

| Context | Bootstrap credential |
|---|---|
| GitHub Actions | **none** — OIDC federation, no stored secret |
| Deployed service | **none** — managed identity assigned to the resource |
| Local development | **none** — your own `az login` session |
| Claude Code session | `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_SECRET` |

Only the last one needs a stored secret, and it reduces the environment
configuration from 33 variables to 3. `push.mjs` refuses to write the `ARM_*`
group unless `--include-bootstrap` is passed, because storing it inside the
vault it unlocks is circular.

## Using it

### Claude Code sessions

Set just `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_SECRET` and
`AZURE_KEY_VAULT_NAME` in the environment configuration, then load the rest on
demand:

```bash
source scripts/secrets/load.sh
```

To load them automatically at session start, add a hook to `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node scripts/secrets/pull.mjs --format env --out \"$HOME/.certainti-secrets.env\" --allow-missing"
          }
        ]
      }
    ]
  }
}
```

and source that file from your shell profile. It is written outside the
repository with mode `0600`. Note this costs one vault round-trip per session
and will fail noisily if the service principal expires, which is why it is
opt-in rather than the default.

### Local development

```bash
az login
export AZURE_KEY_VAULT_NAME=certainti-kv
source scripts/secrets/load.sh
```

No service principal on developer machines — your own identity is the
credential, so access follows your account and is revoked when it is.

### GitHub Actions

Federate once, then no secret is stored in GitHub at all:

```bash
az ad app federated-credential create --id <APP_ID> --parameters '{
  "name": "github-tech-administration-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:certainti-ai/tech_administration:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

The `subject` is matched exactly, so a branch, tag, pull request or environment
each needs its own federated credential. The workflow then needs only three
non-secret ids — see
[`.github/workflows/secrets-check.yml`](../.github/workflows/secrets-check.yml).

### Deployed services

Assign a managed identity to the host, grant it **Key Vault Secrets User**, and
call `pull.mjs` — or the Azure SDK directly — at startup.
`DefaultAzureCredential` picks up the managed identity with no configuration,
which is why the same script works unchanged here.

Note that `@azure/identity` and `@azure/keyvault-secrets` are currently
`devDependencies`, because only the tooling uses them. A deployed service that
fetches its own secrets at startup must move them to `dependencies`.

## Day-to-day

### Add a secret

1. Add an entry to the group in `scripts/secrets/manifest.mjs`.
2. `az keyvault secret set --vault-name certainti-kv --name <name> --value <value>`
3. `node scripts/secrets/check.mjs` to confirm.

Every context picks it up on its next pull; nothing else needs changing.

### Rotate a secret

Set the new value in Key Vault. Key Vault keeps previous versions, so a bad
rotation is recoverable:

```bash
az keyvault secret list-versions --vault-name certainti-kv --name maindb-password
```

Long-running processes cache what they read at startup and need a restart.

### Check for drift

```bash
node scripts/secrets/check.mjs --require-complete
```

Compares the vault against the current environment by digest and reports
`match`, `differ`, `env-missing`, `vault-missing` or `absent-both` per entry —
without revealing either value.

## Known issues in the current inventory

- **`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` hold the same 14-character
  value**, and it carries no `AKIA`/`ASIA` prefix. A real key id is 20
  characters and a real secret is 40, so these are a placeholder or a
  copy-paste error rather than working credentials. Fix or remove them before
  migrating — copying a broken credential into the vault preserves the bug and
  makes it look official.

- **`MAINDB_*` and `ORGDB_*` share bastion host, port, user and password**
  (identical digests), and share a database user. Worth confirming that is
  intended rather than one config having been copied from the other.

- **`TF_VAR_repo_pat` is a long-lived PAT.** A GitHub App installation token is
  short-lived and scopable; prefer it when the Terraform run can be changed.

- **Static AWS keys.** Once the placeholder above is resolved, prefer OIDC
  federation to AWS from GitHub Actions and an instance role in deployed
  services, so no long-lived AWS secret needs to exist.

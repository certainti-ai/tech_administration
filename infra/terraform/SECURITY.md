# Security notes for this configuration

Creating the resource group, Key Vault and SSH key here makes a first
deployment self-contained. It also changes what the Terraform state file is,
and that is worth being explicit about.

## The state file is now sensitive material

Two things put secrets in state:

1. **A generated SSH private key.** `tls_private_key` computes the key inside
   Terraform, so both halves are stored in state. Unavoidable for a generated
   key — it is the reason `admin_ssh_public_key` exists as an input, and why
   supplying your own is preferred for anything long-lived.
2. **The Key Vault secret** holding that private key, stored so it can be
   fetched without reading state at all.

The database passwords do **not** pass through Terraform. They are pushed
separately by `npm run secrets:push` and never appear in this configuration.

**Therefore:** the backend must be remote, encrypted and access-controlled, and
state access should be treated as equivalent to SSH access to the VM. The
`backend "azurerm" {}` block is deliberately empty so it cannot be run with
local state by accident.

To avoid a generated key entirely:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/trd365 -C trd365-maintenance
export TF_VAR_admin_ssh_public_key="$(cat ~/.ssh/trd365.pub)"
```

## Guards against losing the vault

The vault is the source of truth for every database credential, so destroying
it is the worst outcome this configuration can produce. Three things stand in
the way:

| Guard | Effect |
|---|---|
| `prevent_destroy` on the vault | `terraform destroy` fails rather than deleting it |
| `prevent_destroy` on the resource group | a group destroy would take the vault with it |
| `purge_soft_delete_on_destroy = false` | a deleted vault stays recoverable for the retention window |

Removing any of them should be a deliberate, reviewed act.

## Purge protection is a one-way door

`key_vault_purge_protection` defaults to **false**, which is not the end state
you want.

With it on, a soft-deleted vault cannot be purged early — the strongest
protection available, and correct for a vault of production passwords. But it
**cannot be turned off once enabled**, and a destroyed vault's name stays
reserved for the full retention window, so a destroy/recreate cycle fails until
it expires.

Off during bring-up, when you may well tear down and retry. **Turn it on once
the vault holds real secrets**, and accept from that point that the vault is
permanent.

## RBAC, and why the first apply can fail

The vault uses RBAC authorisation rather than access policies. Two assignments
are made:

- **Deployer → Key Vault Secrets Officer**, so it can populate the vault and
  store the SSH key.
- **VM identity → Key Vault Secrets User**, read-only. The VM consumes secrets;
  it never writes them, and cannot rotate them.

Creating either requires the Terraform identity to hold **User Access
Administrator or Owner**, scoped at least to the resource group. **Contributor
cannot create role assignments** — this is the most common first-apply failure,
and it happens late, after the VM is already built.

Azure RBAC is also eventually consistent, so a secret written immediately after
its role assignment usually 403s. `time_sleep.wait_for_vault_rbac` waits 60
seconds for propagation. If the SSH secret still fails to write, re-running
apply is the fix, not a permissions change.

## Network posture

- The VM has **no public IP** and deny-all inbound by default.
- The vault allows public network access by default, because the initial
  `secrets:push` runs from an operator machine. Once the VM is the only
  consumer, set `key_vault_public_network_access = false` and add a private
  endpoint.

## What this configuration deliberately does not do

- It does not create or manage the VNet or subnet. The subnet must already
  exist and must reach the bastion; that is the one input with no default.
- It does not put database credentials into Terraform. They are pushed
  separately, so rotating one is not a `terraform apply`.
- It does not grant the VM write access to the vault. Read-only is the whole
  point of the managed identity.

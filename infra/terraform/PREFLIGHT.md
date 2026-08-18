# Preflight — what is already available, and what is not

Checked against this session's environment on 2026-08-18.

## Already supplied (do not re-enter)

| Input | Source | Status |
|---|---|---|
| Provider auth | `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_SECRET` | present, well-formed |
| `subscription_id` | `ARM_SUBSCRIPTION_ID` | present, valid GUID |
| `location` | derived → `centralus` | read off the database hostnames |

The azurerm provider reads the `ARM_*` variables directly, so `subscription_id`
is now an optional override rather than a required input, and `location`
defaults to the region the databases are actually in.

## Still needed — five values

| Input | Why it cannot be derived |
|---|---|
| `resource_group_name` | Nothing in the environment names one |
| **`subnet_id`** | **The critical one.** Must reach the bastion (172.203.151.166) and trd365ai (4.246.251.140). Discoverable via ARM, which is blocked from this sandbox |
| `key_vault_id` | No vault is named anywhere; `AZURE_KEY_VAULT_NAME` is unset |
| `key_vault_name` | As above |
| `admin_ssh_public_key` | Not present, and should not be — supply your own |

Plus, for remote state: a storage account and container for the backend.

## The easiest way to supply them

Terraform reads `TF_VAR_<name>` environment variables automatically. This
project already carries its database credentials that way, so adding these five
to the same environment configuration means **no tfvars file is needed at all**:

```
TF_VAR_resource_group_name
TF_VAR_subnet_id
TF_VAR_key_vault_id
TF_VAR_key_vault_name
TF_VAR_admin_ssh_public_key
```

`TF_VAR_repo_pat` already follows this pattern, so the mechanism is proven here.

## Two things to settle before applying

1. **Does the Key Vault exist?** Nothing has ever been pushed to one — the
   secrets tooling is built but unrun (`docs/secrets.md`). If no vault exists,
   `key_vault_id` has nothing to point at. Either create it first, or decide
   that this module should create it, which is a deliberate change: it would put
   the vault's lifecycle in the same state file as a VM you may want to rebuild.

2. **Service principal permissions.** `ARM_CLIENT_ID` needs Contributor on the
   resource group *and* **User Access Administrator** (or Owner) scoped to the
   vault — `identity.tf` creates an RBAC role assignment, and Contributor cannot
   write those. This is the most common first-apply failure.

## What could not be checked from here

The sandbox blocks `management.azure.com`, so none of the following could be
confirmed and all are assumptions until `terraform plan` runs:

- whether the resource group, vault or subnet exist
- whether the service principal holds the two roles above
- whether the subnet actually reaches the bastion and trd365ai

`terraform plan` answers the first two. The third is only proven by
`deploy/verify.sh` once the VM exists — which is the main reason to stand it up
early.

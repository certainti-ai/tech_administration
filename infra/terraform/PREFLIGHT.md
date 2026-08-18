# Preflight — what you need before applying

Checked against this session's environment on 2026-08-18.

## Supplied by the environment

| Input | Source |
|---|---|
| Provider auth | `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_SECRET` |
| `subscription_id` | `ARM_SUBSCRIPTION_ID` |
| `location` | derived → `centralus`, from the database hostnames |

## Created for you

| Resource | Notes |
|---|---|
| Resource group | `trd365-maintenance`. `create_resource_group = false` to reuse one |
| Key Vault | Name generated with a random suffix — vault names are globally unique |
| SSH key pair | Generated when none supplied; private half stored in the vault |

## The one input with no default

**`subnet_id`.** An existing subnet that can reach the SSH bastion
(`172.203.151.166`) and `trd365ai` (`4.246.251.140`).

It has no default because there is nothing sensible to guess, and getting it
wrong is the most likely way this deployment disappoints: the VM comes up
healthy and cannot see a single database. Nothing in the configuration can
detect that — only `deploy/verify.sh` can, after the fact.

```bash
export TF_VAR_subnet_id="/subscriptions/.../virtualNetworks/<vnet>/subnets/<subnet>"
```

Plus, for remote state: a storage account and container for the backend.

## Permissions the Terraform identity needs

| Role | Scope | Why |
|---|---|---|
| Contributor | subscription or resource group | Create the group, VM, NIC, NSG, vault |
| **User Access Administrator** or Owner | resource group | **Contributor cannot create role assignments**, and this configuration creates two |

That second row is the most common first-apply failure, and it surfaces late —
after the VM already exists.

## Checked, and what could not be

Verified here:

- HCL parses and is canonically formatted (`terraform fmt`)
- every `var.*`, `local.*`, resource and data reference resolves, and nothing
  declared is unused (static check, since `validate` needs the provider)
- the cloud-init template renders to valid YAML with no unsubstituted variables
- the systemd unit carries its restart, boot-persistence and sandboxing directives

Not verified, because the sandbox blocks `management.azure.com` and
`registry.terraform.io`:

- `terraform validate` and `plan` — the azurerm provider cannot be downloaded
- whether the subnet exists or reaches anything
- whether the service principal holds the two roles above

**Read the plan before applying.** It is the first real check this
configuration has had.

## Order of operations

```bash
export TF_VAR_subnet_id="..."

terraform init -backend-config=...
terraform plan          # read it properly
terraform apply

# then follow the `next_steps` output: populate the vault, fetch the SSH key,
# deploy, and verify the VM can actually reach the databases.
```

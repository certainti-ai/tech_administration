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

---

## Lessons from the sibling deployment (`incentiwise-beta`)

A session in the `incentiwise-beta` environment provisioned a live Azure VM in
**this same subscription** (`b8e81c74…`, "Certainti.Ai - Platform") and tenant
(`b6734060…`) on 2026-08-17. Three of its findings apply directly here.

**1. Dsv5 quota was zero.** In its region the `Dsv5` family had **0 cores**
available while `Dsv3`, `Ev3` and `Dav6` had 10 free. Quota is per family per
region and is not granted by default. `vm_size` therefore defaults to
`Standard_D2s_v3`, not v5. Confirm before applying:

```bash
az vm list-usage --location centralus -o table | grep -i standardd
```

A quota failure surfaces at apply time, after the network and identity exist.

**2. Their service principal had Contributor only.** Verified against ARM. This
configuration creates **two** role assignments, and Contributor cannot create
any. The service principal here is a *different* one (`7b8767e1…` vs their
`8e964b9a…`), so its rights are unknown and unverifiable from the sandbox.

If the apply fails on `Authorization` when creating a role assignment, set
`grant_vm_vault_access = false` and `grant_deployer_vault_access = false` to get
the infrastructure up, then have someone with User Access Administrator run the
command from the `pending_role_assignments` output. **The VM cannot read a
single credential until that is done.**

**3. Region.** They used `eastus`; this defaults to `centralus`, because that is
where the databases are. Check quota in the region you actually use.

### Not a problem here

They had to inject a repo PAT into cloud-init `custom_data` to clone a private
repository, and their handover flags that PAT for revocation.
`certainti-ai/tech_administration` is **public**, so `deploy.sh` clones
anonymously and no credential is baked into the VM's boot configuration.

### Worth acting on separately

Their handover lists two credentials to rotate: a service principal client
secret that was pasted into a chat transcript, and the repo PAT baked into
cloud-init. This environment carries a `TF_VAR_repo_pat` variable — if it is the
same PAT, it should be revoked regardless of this deployment.

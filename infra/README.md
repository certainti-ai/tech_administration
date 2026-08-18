# Infrastructure — the maintenance VM

Terraform for the dedicated maintenance host, plus the scripts that deploy onto
it. Everything specific to Certainti's Azure estate is an input; nothing is
guessed or hardcoded.

> **Nobody has run this yet.** It has been format-checked and the cloud-init
> renders to valid YAML, but `terraform validate` and `plan` could not run here
> — the sandbox blocks `registry.terraform.io`, so the azurerm provider cannot
> be downloaded. **Run `terraform plan` and read it before applying.**

## What it creates

| Resource | Notes |
|---|---|
| Linux VM (Ubuntu 24.04) | Key-only auth; password login disabled |
| User-assigned managed identity | Granted **Key Vault Secrets User**, read-only |
| Network interface + NSG | Deny-all inbound by default; no public IP |
| cloud-init bootstrap | Python 3.12, service account, directories, systemd unit |

## Design decisions worth knowing

**No public IP, deny-all inbound.** A host that can purge production is not
reachable from the internet. Administer it through Azure Bastion or
`az vm run-command`; both work with no inbound rules at all. `assign_public_ip`
exists but defaults to `false`, and `0.0.0.0/0` is rejected outright for SSH.

**Managed identity, not a stored credential.** The VM reads secrets from Key
Vault as itself (PRD FR-5.3). Nothing is written to its disk, and the role is
*Secrets User* — read only. Rotation is an administrator action from elsewhere.

**User-assigned, not system-assigned identity.** It outlives the VM, so
rebuilding the host does not mean recreating the Key Vault role assignment.

**The subnet is the load-bearing input.** It must reach the SSH bastion — and
therefore `maindb` and `orgdb` behind it — and `trd365ai` directly, for every
environment the application monitors. A VM in the wrong subnet comes up unable
to see anything, and that is the most likely way this goes wrong.

**The service is installed but not started.** Its entry point
(`trd365_orchestrator`) arrives in Phase 2. cloud-init enables the unit so it
survives reboot, and `deploy.sh` starts it only once the module actually exists
— starting it now would just produce a restart loop in the journal.

## Use

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill it in; it is gitignored

# State holds identity and role assignments — keep it remote, not on a laptop.
terraform init \
  -backend-config="resource_group_name=<rg>" \
  -backend-config="storage_account_name=<sa>" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=maintenance-vm.tfstate"

terraform plan      # read this properly before the next line
terraform apply
```

Credentials come from `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` /
`ARM_SUBSCRIPTION_ID`, or from a managed identity in CI.

## Deploying the application

```bash
az vm run-command invoke -g <rg> -n <vm> --command-id RunShellScript \
  --scripts 'sudo -u trd365 /opt/trd365/deploy.sh'
```

or run `.github/workflows/deploy.yml` — manual trigger only, OIDC, no stored
credential. Nothing deploys automatically on a commit landing; this host can
purge production.

`deploy.sh` is idempotent — re-running it is how you ship a new revision. It
hard-resets to `origin/<branch>` rather than merging: the VM is a deployment
target, never somewhere edits are made, so local divergence is corruption.

## Verifying

```bash
az vm run-command invoke -g <rg> -n <vm> --command-id RunShellScript \
  --scripts 'sudo /opt/trd365/verify.sh'
```

`verify.sh` is read-only and answers the question no Claude session could:
**can this host actually see the databases?** It checks the managed identity can
get a Key Vault token, that `trd365_core` imports, and that all three
production databases answer an identity query through the bastion.

That check is the immediate reason to stand this VM up, well before the
application exists.

## Layout

```
terraform/
  versions.tf              provider + remote state backend
  variables.tf             every input, all documented
  main.tf                  the VM
  network.tf               NIC, NSG, optional public IP
  identity.tf              managed identity + Key Vault role
  cloud-init.yaml.tftpl    bootstrap and systemd unit
  outputs.tf
  terraform.tfvars.example
deploy/
  deploy.sh                install or update the application
  verify.sh                read-only post-deploy checks
```

## Still needed

See [`PREFLIGHT.md`](terraform/PREFLIGHT.md) for what the environment already
supplies and what it does not.

Short version: authentication and `subscription_id` come from the `ARM_*`
variables already present, and `location` defaults to `centralus` (read off the
database hostnames). **Five values remain**: `resource_group_name`, `subnet_id`,
`key_vault_id`, `key_vault_name`, `admin_ssh_public_key` — supplied most easily
as `TF_VAR_*` environment variables, the way this project already supplies its
database credentials.

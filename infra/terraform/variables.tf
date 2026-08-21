# ---------------------------------------------------------------------------
# Every value that is specific to Certainti's Azure estate is an input. None is
# guessed or hardcoded — see terraform.tfvars.example and docs/HANDOFF.md §6.
# ---------------------------------------------------------------------------

variable "subscription_id" {
  description = <<-EOT
    Azure subscription. Leave unset in normal use: the azurerm provider reads
    ARM_SUBSCRIPTION_ID from the environment, which is where this project's
    credentials already live. Set it only to target a different subscription
    than the one those credentials default to.
  EOT
  type        = string
  default     = null
}

variable "resource_group_name" {
  description = "Name of the resource group. Created unless create_resource_group is false."
  type        = string
  default     = "trd365-maintenance"
}

variable "create_resource_group" {
  description = <<-EOT
    Create the resource group (default), or use an existing one of that name.

    Set false when the maintenance VM belongs alongside other platform
    resources — creating the group means Terraform owns its lifecycle, and a
    group destroy takes everything inside it.
  EOT
  type        = bool
  default     = true
}

variable "location" {
  description = <<-EOT
    Azure region. Defaults to the region the databases are actually in, read off
    their hostnames (prod-thinkrd365-psqlserver-**centralus**-pvt-main), so the
    VM does not sit a continent away from every query it makes. Override only if
    the maintenance host belongs somewhere else on purpose.
  EOT
  type        = string
  default     = "centralus"
}

variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
  default     = "trd365-maint"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.name_prefix))
    error_message = "name_prefix must be 3-20 characters of lowercase letters, digits or hyphens."
  }
}

# --------------------------------------------------------------------- network

variable "subnet_id" {
  description = <<-EOT
    Resource id of an existing subnet to join, instead of the one this stack
    creates. Leave null — the default — and the stack builds its own network.

    Self-contained is the intended posture. This application administers the
    platform's databases but is not part of the platform: it creates its own
    resource group, network, vault and host, and it changes nothing that already
    exists. It reaches every database over public endpoints — an SSH tunnel to
    the bastion for maindb/orgdb, and a public address for trd365ai — which is
    the same path the operator scripts already take from a laptop. So it needs
    outbound internet and nothing else: no VNet peering, no private DNS, no
    change to anybody else's network.

    Set this only if you have decided the host belongs inside an existing
    network, and accept the coupling that comes with it.
  EOT
  type        = string
  default     = null
}

variable "vnet_address_space" {
  description = <<-EOT
    Address space for the VNet this stack creates. Ignored when subnet_id is set.

    Unroutable to anything else by design. Nothing peers with this network, so
    the range only has to avoid colliding with whatever the VM reaches over a
    VPN, if you ever add one.
  EOT
  type        = list(string)
  default     = ["10.80.0.0/16"]
}

variable "subnet_address_prefix" {
  description = "Address prefix for the VM subnet. Ignored when subnet_id is set."
  type        = string
  default     = "10.80.1.0/24"
}

# ------------------------------------------------------------- public access

variable "expose_publicly" {
  description = <<-EOT
    Put the application on the public internet behind a Caddy login.

    Off by default, and the default is the right posture: this host holds
    credentials that can delete production data. Turning it on creates a public
    IP, opens 80 and 443 to the world, and installs Caddy in front of the
    service with HTTP basic authentication.

    What makes that defensible is the identity Caddy hands upstream. It injects
    the **viewer** role and nothing else, and the service refuses to start any
    utility that writes without operator or admin (`can_run` in
    `trd365_orchestrator.security`). Every registered utility writes. So the
    exposed surface can read health, the utility catalogue, the audit trail and
    the data model, and cannot run anything at all — by construction, not by
    trusting whoever gets through the login.

    It remains a demonstration posture. Basic auth is one shared secret with no
    audit of who used it, and the header authenticator it feeds exists for
    development. For real use, wire Entra ID SSO (PRD FR-3.x) and turn this off.
  EOT
  type        = bool
  default     = false
}

variable "demo_username" {
  description = "Username for the Caddy login. Only used when expose_publicly is set."
  type        = string
  default     = "demo"
}

variable "demo_roles" {
  description = <<-EOT
    The roles Caddy injects for whoever gets through the login.

    `viewer` is the safe default and the one to come back to: it can read
    everything and start nothing.

    `operator` lets the login start utilities. What keeps that defensible is not
    the login — it is that an operator cannot finish anything consequential
    alone:

      * a production run that writes waits for a second person, and
        self-approval is refused (`can_approve`, PRD FR-4.3);
      * a production *preview* of the project purges waits too, because their
        preview executes the delete-and-recompute and rolls it back rather than
        counting rows (`dry_run_executes`);
      * dev, QA and stage have no credentials in this deployment, so an apply
        there fails at connect.

    So an operator through this login can preview freely, and every production
    write still needs somebody who is not them. Add `approver` only if you
    intend this login to be able to complete production writes by itself — with
    one shared password, that is not a posture to hold for long.
  EOT
  type        = string
  default     = "viewer"

  validation {
    condition     = alltrue([for r in split(",", var.demo_roles) : contains(["viewer", "operator", "approver", "admin"], trimspace(r))])
    error_message = "demo_roles must be a comma-separated list of viewer, operator, approver or admin."
  }
}

variable "demo_password" {
  description = <<-EOT
    Password for the Caddy login. Only used when expose_publicly is set.

    Stored as a bcrypt hash on the VM, never in plain text, and never written to
    the repository. It is still one shared secret on a publicly reachable host,
    so treat it as a demo credential with a short life.
  EOT
  type        = string
  default     = null
  sensitive   = true
}

variable "public_hostname" {
  description = <<-EOT
    DNS name to serve on, for a real TLS certificate.

    Leave empty and the deployment uses `<dashed-ip>.nip.io`, which resolves to
    the public IP without any DNS work and lets Caddy obtain a genuine
    Let's Encrypt certificate — so the login page is not behind a browser
    warning, which matters when the thing being typed into it is a password.

    Set it to a name you control (`techadmin.certainti.ai`) once its A record
    points at the public IP.
  EOT
  type        = string
  default     = ""
}

variable "assign_public_ip" {
  description = <<-EOT
    Whether to attach a public IP. Defaults to false.

    A maintenance host that can purge production should not be reachable from
    the internet. Reach it through Azure Bastion, a jump host, or
    `az vm run-command`, all of which work without one.
  EOT
  type        = bool
  default     = false
}

variable "allowed_ssh_source_prefixes" {
  description = <<-EOT
    CIDR ranges permitted to reach TCP 22, used only when assign_public_ip is
    true. Deliberately has no default: an empty list denies all inbound SSH,
    which is the correct posture for a private VM.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.allowed_ssh_source_prefixes, "0.0.0.0/0")
    error_message = "Refusing 0.0.0.0/0 for SSH on a host that can write to production."
  }
}

variable "auto_deploy_schedule" {
  description = <<-EOT
    systemd OnCalendar expression for self-updating deploys. Every three hours
    by default; set to "" to disable and deploy by hand.

    The timer runs deploy.sh, which fetches the deployed branch, installs it, and
    restarts the service **only if the test suite passes** — otherwise it rolls
    the checkout back and leaves the running service where it was. That gate
    matters here: this host holds credentials that can delete production data, so
    a bad commit arriving unattended must not end up serving.
  EOT
  type        = string
  default     = "*-*-* 00/3:00:00"
}

variable "app_port" {
  description = "Port the application listens on, reachable only inside the VNet."
  type        = number
  default     = 8080
}

variable "allowed_app_source_prefixes" {
  description = "CIDR ranges permitted to reach app_port. Keep this to the VNet or a proxy subnet."
  type        = list(string)
  default     = []
}

# ------------------------------------------------------------------------- vm

variable "vm_size" {
  description = <<-EOT
    VM size. The workload is long-running database jobs — mostly waiting on IO,
    occasionally holding a large result set — so memory matters more than cores.

    Defaults to a v3 rather than the newer v5. A sibling deployment in this same
    subscription found the Dsv5 quota was **zero** in its region while Dsv3,
    Ev3 and Dav6 had free cores; quota is per family per region and is not
    granted by default. Check before changing family:

      az vm list-usage --location <region> -o table | grep -i standardd

    A quota failure surfaces at apply time, after the network and identity are
    already created.
  EOT
  type        = string
  default     = "Standard_D2s_v3"
}

variable "admin_username" {
  description = "Local administrator account name."
  type        = string
  default     = "trd365admin"
}

variable "admin_ssh_public_key" {
  description = <<-EOT
    SSH public key for the administrator account. Password authentication is
    disabled unconditionally, so this is the only interactive route in.

    Left unset, a key pair is generated and its private half stored in the Key
    Vault. Supplying your own is preferred for anything long-lived: a generated
    key's private half necessarily lands in Terraform state.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.admin_ssh_public_key == null ? true : can(regex("^(ssh-rsa|ssh-ed25519|ecdsa-sha2-)", var.admin_ssh_public_key))
    error_message = "admin_ssh_public_key must be an OpenSSH public key, not a path or a private key."
  }
}

variable "os_disk_size_gb" {
  description = "OS disk size. Reports, model snapshots and audit logs accumulate here."
  type        = number
  default     = 64
}

# -------------------------------------------------------------------- key vault

variable "create_key_vault" {
  description = <<-EOT
    Create the Key Vault (default), or point at an existing one via
    existing_key_vault_id.

    Creating it means this state file governs a vault of production database
    credentials. That is why the vault carries prevent_destroy, and why the
    backend must be remote and access-controlled — see SECURITY.md.
  EOT
  type        = bool
  default     = true
}

variable "key_vault_name" {
  description = <<-EOT
    Key Vault name. Left unset, one is generated from name_prefix with a random
    suffix, because vault names are globally unique across all of Azure and a
    fixed name eventually collides with someone else's.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.key_vault_name == null ? true : can(regex("^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$", var.key_vault_name))
    error_message = "Key Vault names are 3-24 chars, alphanumeric and hyphens, starting with a letter."
  }
}

variable "existing_key_vault_id" {
  description = "Resource id of an existing vault. Only used when create_key_vault is false."
  type        = string
  default     = null
}

variable "key_vault_soft_delete_retention_days" {
  description = "Recovery window for deleted secrets and for the vault itself (7-90)."
  type        = number
  default     = 90

  validation {
    condition     = var.key_vault_soft_delete_retention_days >= 7 && var.key_vault_soft_delete_retention_days <= 90
    error_message = "Azure permits 7 to 90 days."
  }
}

variable "key_vault_purge_protection" {
  description = <<-EOT
    Enable purge protection. Correct end state for a vault holding production
    credentials, but a ONE-WAY DOOR: it cannot be disabled afterwards, and a
    destroyed vault's name stays reserved for the whole retention window, so
    destroy/recreate cycles fail.

    Default is off so a first deployment can be iterated on. Turn it on once the
    vault holds real secrets.
  EOT
  type        = bool
  default     = false
}

variable "key_vault_public_network_access" {
  description = <<-EOT
    Allow reaching the vault from outside the VNet. Needs to be true for the
    initial `secrets:push` from an operator machine; consider turning it off,
    with a private endpoint, once the VM is the only consumer.
  EOT
  type        = bool
  default     = true
}

variable "grant_vm_vault_access" {
  description = <<-EOT
    Grant the VM's managed identity 'Key Vault Secrets User' on the vault.

    True is correct, and the VM cannot read a single credential without it. It
    is a variable because creating a role assignment needs User Access
    Administrator or Owner, and a sibling deployment in this subscription found
    the service principal had **Contributor only** — which cannot create role
    assignments at all.

    Set false to let a Contributor-only identity complete the apply, then have
    someone with rights run the command printed by the `pending_role_assignments`
    output. The VM will not work until they do.
  EOT
  type        = bool
  default     = true
}

variable "grant_deployer_vault_access" {
  description = <<-EOT
    Grant the identity running Terraform 'Key Vault Secrets Officer' on the new
    vault, so it can populate it and store the generated SSH key.

    Requires that identity to hold User Access Administrator or Owner —
    Contributor alone cannot create role assignments.
  EOT
  type        = bool
  default     = true
}

variable "store_ssh_key_in_vault" {
  description = "Store a generated SSH private key in the vault, so it need not be read from state."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------ misc

variable "app_repository_url" {
  description = "HTTPS clone URL of this repository, used by the deploy script."
  type        = string
  default     = "https://github.com/certainti-ai/tech_administration.git"
}

variable "app_branch" {
  description = <<-EOT
    Branch the VM deploys from.

    Defaults to the branch this work actually lives on, because that is the one
    that exists: the repository has no `main` yet, and cloud-init's clone fails
    outright against a branch that is not there. **Change this to `main` when
    this branch merges** — a default naming a feature branch is a temporary
    state, not the intended one.
  EOT
  type        = string
  default     = "claude/certainti-tech-admin-y4c4ul"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    application = "tech-administration"
    component   = "maintenance-vm"
    managed_by  = "terraform"
  }
}

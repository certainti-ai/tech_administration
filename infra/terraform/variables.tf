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
  description = "Existing resource group to create resources in."
  type        = string
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
    Resource id of the existing subnet the VM joins.

    This is the load-bearing input: the subnet must be able to reach the SSH
    bastion (and therefore maindb/orgdb behind it) and trd365ai directly, for
    every environment the application monitors. A VM in the wrong subnet is the
    single most likely reason a deployment comes up unable to see anything.
  EOT
  type        = string
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
  EOT
  type        = string
  default     = "Standard_D2s_v5"
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
  EOT
  type        = string

  validation {
    condition     = can(regex("^(ssh-rsa|ssh-ed25519|ecdsa-sha2-)", var.admin_ssh_public_key))
    error_message = "admin_ssh_public_key must be an OpenSSH public key, not a path or a private key."
  }
}

variable "os_disk_size_gb" {
  description = "OS disk size. Reports, model snapshots and audit logs accumulate here."
  type        = number
  default     = 64
}

# -------------------------------------------------------------------- key vault

variable "key_vault_id" {
  description = <<-EOT
    Resource id of the Key Vault holding the database credentials.

    The VM's managed identity is granted 'Key Vault Secrets User' on it — read
    only, and no credential is ever written to the VM's disk (PRD FR-5.3).
  EOT
  type        = string
}

variable "key_vault_name" {
  description = "Key Vault name, passed to the app as AZURE_KEY_VAULT_NAME."
  type        = string
}

# ------------------------------------------------------------------------ misc

variable "app_repository_url" {
  description = "HTTPS clone URL of this repository, used by the deploy script."
  type        = string
  default     = "https://github.com/certainti-ai/tech_administration.git"
}

variable "app_branch" {
  description = "Branch the VM deploys from."
  type        = string
  default     = "main"
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

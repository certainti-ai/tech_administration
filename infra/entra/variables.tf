# ---------------------------------------------------------------------------
# Inputs. Only two have no default — the vault to write the secrets into and the
# hostname the browser will be redirected back to — because getting either wrong
# is the kind of mistake that fails at sign-in time rather than at apply time.
# ---------------------------------------------------------------------------

variable "tenant_id" {
  description = <<-EOT
    Entra ID tenant. Defaults to certainti.ai, which is also the value the
    application checks the `tid` claim against, so the two cannot drift.
  EOT
  type        = string
  default     = "b6734060-665c-4b7b-94e2-716458c1d933"
}

variable "subscription_id" {
  description = <<-EOT
    Subscription holding the Key Vault. Leave unset to use whatever the azurerm
    provider already resolves from the environment or `az account show`.
  EOT
  type        = string
  default     = null
}

variable "public_hostname" {
  description = <<-EOT
    The name Caddy serves, without a scheme. The redirect URI is derived from it
    as https://<host>/auth/callback and registered on the application.

    This must be the same value as `public_hostname` in infra/terraform. If they
    disagree, Microsoft returns AADSTS50011 (redirect URI mismatch) at sign-in
    with nothing in any log on this side to explain it.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.public_hostname))
    error_message = "A bare hostname, lowercase, no scheme and no trailing slash."
  }
}

variable "display_name" {
  description = "What the application is called in the Entra admin centre and on the consent screen."
  type        = string
  default     = "Certainti Tech Administration"
}

# ---------------------------------------------------------------------------
# where the secrets go
# ---------------------------------------------------------------------------

variable "key_vault_name" {
  description = <<-EOT
    The maintenance vault — the one the VM's managed identity already reads.
    Both secrets are written into it under the names the service expects,
    `entra-client-secret` and `session-signing-secret`.

    Applying this needs Key Vault Secrets Officer on that vault. If you would
    rather not hold it, set `write_secrets_to_vault = false` and the module
    prints the secret as a sensitive output for you to store yourself.
  EOT
  type        = string
}

variable "key_vault_resource_group_name" {
  description = "Resource group the vault is in."
  type        = string
  default     = "trd365-maintenance"
}

variable "write_secrets_to_vault" {
  description = <<-EOT
    Write both secrets into the vault (default). Turn off only if the identity
    applying this has directory rights but not vault rights — then read them from
    the outputs and set them with `az keyvault secret set` as somebody who does.
  EOT
  type        = bool
  default     = true
}

variable "secret_valid_days" {
  description = <<-EOT
    Lifetime of the client secret. Two years is Entra's own default for a new
    secret and long enough that rotation is a scheduled task rather than a
    surprise; shorten it if your policy says so.

    Rotate with `terraform apply -replace azuread_application_password.console`,
    which mints the new one and rewrites the vault in the same apply. `end_date`
    is otherwise ignored, so a plan never proposes rotation on its own.
  EOT
  type        = number
  default     = 730

  validation {
    condition     = var.secret_valid_days > 0 && var.secret_valid_days <= 730
    error_message = "Between 1 and 730 days; Entra refuses longer."
  }
}

# ---------------------------------------------------------------------------
# assignments (all optional — see README)
# ---------------------------------------------------------------------------

variable "viewer_group_ids" {
  description = <<-EOT
    Object ids of security groups to assign each role to. Object ids, not names
    and not display names: `az ad group show -g "Platform Team" --query id -o tsv`.

    Left empty — the default — nobody is assigned, and because the service
    principal requires assignment, nobody can sign in until somebody assigns
    them here or in the portal. That is the intended starting state.
  EOT
  type        = list(string)
  default     = []
}

variable "operator_group_ids" {
  description = "Groups that may start utility runs. See viewer_group_ids."
  type        = list(string)
  default     = []
}

variable "approver_group_ids" {
  description = "Groups that may approve somebody else's production run. See viewer_group_ids."
  type        = list(string)
  default     = []
}

variable "admin_group_ids" {
  description = <<-EOT
    Groups holding operator and approver at once. See viewer_group_ids.

    This is the one combination that lets a single person complete a production
    deletion with nobody else involved. A group, not a team's worth of people.
  EOT
  type        = list(string)
  default     = []
}

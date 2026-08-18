# Key Vault holding the database credentials.
#
# Created here so a first deployment needs nothing to exist beforehand. That
# puts a vault of production credentials in this state file, which drives most
# of the choices below.

resource "random_string" "vault_suffix" {
  count = var.key_vault_name == null ? 1 : 0

  # Key Vault names are globally unique across all of Azure, so a fixed name
  # will eventually collide with someone else's. A suffix avoids that without
  # making the name unreadable.
  length  = 6
  special = false
  upper   = false
  numeric = true
}

locals {
  key_vault_name = coalesce(
    var.key_vault_name,
    substr("${var.name_prefix}-kv-${try(random_string.vault_suffix[0].result, "")}", 0, 24),
  )
}

resource "azurerm_key_vault" "maintenance" {
  count = var.create_key_vault ? 1 : 0

  name                = local.key_vault_name
  location            = var.location
  resource_group_name = local.resource_group_name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  tags                = var.tags

  # RBAC rather than legacy access policies: it is what lets the VM's managed
  # identity and the deployer be granted different levels of access, and what
  # identity.tf assumes.
  enable_rbac_authorization = true

  # Soft delete is mandatory on Azure and is the recovery window if a secret or
  # the vault itself is deleted by mistake.
  soft_delete_retention_days = var.key_vault_soft_delete_retention_days

  # Purge protection makes soft-deleted vaults unrecoverable-by-deletion for the
  # full retention window. It is the right end state for a vault holding
  # production database passwords, but it is a ONE-WAY DOOR: once enabled it
  # cannot be turned off, and a destroyed vault's name stays reserved until the
  # window expires, so a destroy/recreate cycle will fail. Default is off so a
  # first deployment can be iterated on; turn it on once the vault holds real
  # secrets. See SECURITY.md.
  purge_protection_enabled = var.key_vault_purge_protection

  public_network_access_enabled = var.key_vault_public_network_access

  network_acls {
    bypass         = "AzureServices"
    default_action = var.key_vault_public_network_access ? "Allow" : "Deny"
  }

  lifecycle {
    # This vault is the source of truth for every database credential. Losing it
    # to a stray `terraform destroy` would be the worst outcome this
    # configuration can produce, so destroying it has to be a deliberate act:
    # remove this block first.
    prevent_destroy = true
  }
}

locals {
  key_vault_id  = var.create_key_vault ? azurerm_key_vault.maintenance[0].id : var.existing_key_vault_id
  key_vault_uri = var.create_key_vault ? azurerm_key_vault.maintenance[0].vault_uri : null
}

# The deployer needs write access to populate the vault (`npm run secrets:push`)
# and to store the generated SSH private key below. The VM only ever reads —
# that grant lives in identity.tf.
resource "azurerm_role_assignment" "deployer_secrets_officer" {
  count = var.create_key_vault && var.grant_deployer_vault_access ? 1 : 0

  scope                = azurerm_key_vault.maintenance[0].id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Azure RBAC is eventually consistent: a secret written immediately after the
# role assignment is created usually fails with 403. This wait is the
# difference between a first apply that works and one that has to be re-run.
resource "time_sleep" "wait_for_vault_rbac" {
  count = var.create_key_vault && var.grant_deployer_vault_access ? 1 : 0

  depends_on      = [azurerm_role_assignment.deployer_secrets_officer]
  create_duration = "60s"
}

# Managed identity, so no credential is stored on the VM (PRD FR-5.3).
#
# A user-assigned identity rather than system-assigned: it survives the VM being
# rebuilt, so the Key Vault role assignment does not have to be recreated every
# time the host is replaced.

resource "azurerm_user_assigned_identity" "vm" {
  name                = "${var.name_prefix}-identity"
  location            = var.location
  resource_group_name = local.resource_group_name
  tags                = var.tags
}

# Read-only. The VM consumes secrets; it never writes them. Rotation is an
# administrator action from a machine with Secrets Officer, not something the
# maintenance host can do.
resource "azurerm_role_assignment" "key_vault_secrets_user" {
  count = var.grant_vm_vault_access ? 1 : 0

  scope                = local.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.vm.principal_id
}

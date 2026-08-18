# SSH key for the VM's administrator account.
#
# Generated when none is supplied, so a first deployment needs nothing prepared.
# Supplying your own via admin_ssh_public_key is preferred for anything
# long-lived: a generated key's private half is necessarily written to Terraform
# state (see SECURITY.md).

resource "tls_private_key" "admin" {
  count = var.admin_ssh_public_key == null ? 1 : 0

  # RSA 4096 rather than ed25519: universally accepted by Azure Linux images and
  # by every client that might need to reach this host. Not the most modern
  # choice, but the one least likely to fail at an inconvenient moment.
  algorithm = "RSA"
  rsa_bits  = 4096
}

locals {
  admin_ssh_public_key = coalesce(
    var.admin_ssh_public_key,
    try(tls_private_key.admin[0].public_key_openssh, null),
  )
  generated_ssh_key = var.admin_ssh_public_key == null
}

# Store the generated private key in the vault, so an authorised person can
# retrieve it without being handed Terraform state.
#
#   az keyvault secret show --vault-name <vault> \
#     --name maintenance-vm-ssh-private-key --query value -o tsv > ~/.ssh/trd365
#   chmod 600 ~/.ssh/trd365
resource "azurerm_key_vault_secret" "admin_ssh_private_key" {
  count = local.generated_ssh_key && var.create_key_vault && var.store_ssh_key_in_vault ? 1 : 0

  name         = "maintenance-vm-ssh-private-key"
  value        = tls_private_key.admin[0].private_key_openssh
  key_vault_id = azurerm_key_vault.maintenance[0].id
  content_type = "application/x-openssh-private-key"
  tags         = var.tags

  # Both dependencies matter: the role assignment grants the write, and the wait
  # lets Azure RBAC catch up before it is attempted.
  depends_on = [
    azurerm_role_assignment.deployer_secrets_officer,
    time_sleep.wait_for_vault_rbac,
  ]
}

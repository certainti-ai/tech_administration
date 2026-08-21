# The maintenance VM itself.

resource "azurerm_linux_virtual_machine" "maintenance" {
  name                = "${var.name_prefix}-vm"
  location            = var.location
  resource_group_name = local.resource_group_name
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = var.tags

  network_interface_ids = [azurerm_network_interface.vm.id]

  # Key-only. A password on a host that can purge production is not a trade
  # worth making, and the managed identity covers automated access.
  disable_password_authentication = true

  admin_ssh_key {
    username   = var.admin_username
    public_key = local.admin_ssh_public_key
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.vm.id]
  }

  os_disk {
    name                 = "${var.name_prefix}-osdisk"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  boot_diagnostics {}

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    admin_username         = var.admin_username
    app_port               = var.app_port
    auto_deploy_schedule   = var.auto_deploy_schedule
    expose_publicly        = var.expose_publicly
    caddy_site             = local.caddy_site
    demo_username          = var.expose_publicly ? var.demo_username : ""
    demo_password          = var.expose_publicly ? coalesce(var.demo_password, "") : ""
    entra_tenant_id        = var.entra_tenant_id
    entra_client_id        = var.entra_client_id
    entra_group_roles      = var.entra_group_roles
    entra_redirect_uri     = local.entra_redirect_uri
    caddy_auth_block       = local.caddy_auth_block
    caddy_identity_headers = local.caddy_identity_headers
    key_vault_name         = local.key_vault_name
    client_id              = azurerm_user_assigned_identity.vm.client_id
    repository_url         = var.app_repository_url
    branch                 = var.app_branch
  }))

  lifecycle {
    # Rebuilding the host on an image refresh would discard local model
    # snapshots and audit logs. Replace deliberately, having moved those first.
    ignore_changes = [source_image_reference]
  }
}

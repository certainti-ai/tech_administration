# Resource group.
#
# Created by default, so a first deployment needs nothing to exist beforehand.
# Point at an existing group by setting create_resource_group = false, which is
# what you want if the maintenance VM belongs alongside other platform
# resources.

resource "azurerm_resource_group" "maintenance" {
  count = var.create_resource_group ? 1 : 0

  name     = var.resource_group_name
  location = var.location
  tags     = var.tags

  lifecycle {
    # A resource group destroy takes everything inside it with it, including
    # the Key Vault below. Removing this guard should be a deliberate act.
    prevent_destroy = true
  }
}

data "azurerm_resource_group" "existing" {
  count = var.create_resource_group ? 0 : 1
  name  = var.resource_group_name
}

locals {
  resource_group_name = var.create_resource_group ? azurerm_resource_group.maintenance[0].name : data.azurerm_resource_group.existing[0].name
}

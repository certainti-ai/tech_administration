# The maintenance network.
#
# Created by this stack, not borrowed. The application administers the
# platform's databases but is not part of the platform: nothing here peers with
# another network, resolves through somebody else's private DNS, or requires a
# change to infrastructure that already exists.
#
# That works because every database is reachable over a public endpoint today —
# maindb and orgdb through an SSH tunnel to the bastion, trd365ai directly — and
# that is already how the operator scripts connect from a laptop. Outbound
# internet is the only network dependency.
#
# Set var.subnet_id to opt out and join an existing subnet instead.

locals {
  create_network = var.subnet_id == null
  subnet_id      = local.create_network ? azurerm_subnet.vm[0].id : var.subnet_id
}

resource "azurerm_virtual_network" "vm" {
  count = local.create_network ? 1 : 0

  name                = "${var.name_prefix}-vnet"
  address_space       = var.vnet_address_space
  location            = var.location
  resource_group_name = local.resource_group_name
  tags                = var.tags
}

resource "azurerm_subnet" "vm" {
  count = local.create_network ? 1 : 0

  name                 = "${var.name_prefix}-subnet"
  resource_group_name  = local.resource_group_name
  virtual_network_name = azurerm_virtual_network.vm[0].name
  address_prefixes     = [var.subnet_address_prefix]
}

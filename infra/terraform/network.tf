# Network interface and security group.
#
# Default posture is deny-all inbound: a host that can purge production is not
# reachable from the internet, and is administered through Azure Bastion or
# `az vm run-command`. Both SSH and the application port are opt-in and require
# an explicit source range.

resource "azurerm_network_security_group" "vm" {
  name                = "${var.name_prefix}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_network_security_rule" "ssh" {
  count = var.assign_public_ip && length(var.allowed_ssh_source_prefixes) > 0 ? 1 : 0

  name                        = "allow-ssh"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.vm.name
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "22"
  source_address_prefixes     = var.allowed_ssh_source_prefixes
  destination_address_prefix  = "*"
}

resource "azurerm_network_security_rule" "app" {
  count = length(var.allowed_app_source_prefixes) > 0 ? 1 : 0

  name                        = "allow-app"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.vm.name
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.app_port)
  source_address_prefixes     = var.allowed_app_source_prefixes
  destination_address_prefix  = "*"
}

# Explicit terminal deny. Azure's default rules already deny internet inbound,
# but stating it means a future permissive rule has to outrank something visible
# rather than slipping in above an implicit default.
resource "azurerm_network_security_rule" "deny_all_inbound" {
  name                        = "deny-all-inbound"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.vm.name
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
}

resource "azurerm_public_ip" "vm" {
  count = var.assign_public_ip ? 1 : 0

  name                = "${var.name_prefix}-pip"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_interface" "vm" {
  name                = "${var.name_prefix}-nic"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = var.assign_public_ip ? azurerm_public_ip.vm[0].id : null
  }
}

resource "azurerm_network_interface_security_group_association" "vm" {
  network_interface_id      = azurerm_network_interface.vm.id
  network_security_group_id = azurerm_network_security_group.vm.id
}

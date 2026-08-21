# Network interface and security group.
#
# Default posture is deny-all inbound: a host that can purge production is not
# reachable from the internet, and is administered through Azure Bastion or
# `az vm run-command`. Both SSH and the application port are opt-in and require
# an explicit source range.

resource "azurerm_network_security_group" "vm" {
  name                = "${var.name_prefix}-nsg"
  location            = var.location
  resource_group_name = local.resource_group_name
  tags                = var.tags
}

resource "azurerm_network_security_rule" "ssh" {
  count = var.assign_public_ip && length(var.allowed_ssh_source_prefixes) > 0 ? 1 : 0

  name                        = "allow-ssh"
  resource_group_name         = local.resource_group_name
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
  resource_group_name         = local.resource_group_name
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

# Public web access, only when deliberately switched on. Caddy terminates TLS
# and authenticates; the service itself is never reachable directly, because 8080
# is not opened here and Caddy proxies to it over loopback.
resource "azurerm_network_security_rule" "web" {
  for_each = var.expose_publicly ? { http = 80, https = 443 } : {}

  name                        = "allow-${each.key}"
  resource_group_name         = local.resource_group_name
  network_security_group_name = azurerm_network_security_group.vm.name
  priority                    = each.value == 443 ? 120 : 121
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(each.value)
  source_address_prefix       = "Internet"
  destination_address_prefix  = "*"
}

# Explicit terminal deny. Azure's default rules already deny internet inbound,
# but stating it means a future permissive rule has to outrank something visible
# rather than slipping in above an implicit default.
resource "azurerm_network_security_rule" "deny_all_inbound" {
  name                        = "deny-all-inbound"
  resource_group_name         = local.resource_group_name
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

locals {
  # Either switch needs an address; expose_publicly is the ordinary way in.
  public_ip = var.assign_public_ip || var.expose_publicly

  # What Caddy serves on. A name the owner controls if one is given; otherwise
  # the allocated address via nip.io, which resolves to it without any DNS work
  # and still lets Caddy obtain a real certificate — so a password is not typed
  # into a page sitting behind a browser warning.
  allocated_ip = local.public_ip ? azurerm_public_ip.vm[0].ip_address : ""
  # Whether the application authenticates for itself.
  entra_enabled = var.entra_tenant_id != ""

  # The Caddyfile's authentication stanza, or nothing. Assembled here rather than
  # conditionally inside the template because these are multi-line and an HCL
  # string literal cannot span lines.
  caddy_auth_block = local.entra_enabled ? "" : <<-EOT
        basic_auth {
          {$TRD365_DEMO_USER} {$TRD365_DEMO_HASH}
        }
  EOT

  caddy_identity_headers = local.entra_enabled ? "" : <<-EOT
          header_up X-Dev-User {http.auth.user.id}
          header_up X-Dev-Roles ${var.demo_roles}
  EOT

  # Where Entra sends the browser back. Derived from the site Caddy serves rather
  # than configured separately, because the two disagreeing is a sign-in that fails
  # with a redirect-URI mismatch and no obvious cause.
  entra_redirect_uri = (
    local.entra_enabled && local.caddy_site_computed != ""
    ? "https://${local.caddy_site_computed}/auth/callback"
    : ""
  )

  caddy_site_computed = (
    var.public_hostname != "" ? var.public_hostname :
    local.allocated_ip != "" ? "${replace(local.allocated_ip, ".", "-")}.nip.io" : ""
  )
  caddy_site = local.caddy_site_computed
}

resource "azurerm_public_ip" "vm" {
  count = local.public_ip ? 1 : 0

  name                = "${var.name_prefix}-pip"
  location            = var.location
  resource_group_name = local.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_interface" "vm" {
  name                = "${var.name_prefix}-nic"
  location            = var.location
  resource_group_name = local.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = local.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = local.public_ip ? azurerm_public_ip.vm[0].id : null
  }
}

resource "azurerm_network_interface_security_group_association" "vm" {
  network_interface_id      = azurerm_network_interface.vm.id
  network_security_group_id = azurerm_network_security_group.vm.id
}

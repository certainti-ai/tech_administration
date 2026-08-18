output "vm_name" {
  description = "Name of the maintenance VM, for `az vm run-command` and deploys."
  value       = azurerm_linux_virtual_machine.maintenance.name
}

output "resource_group_name" {
  value = var.resource_group_name
}

output "private_ip_address" {
  description = "The address to reach the application on from inside the VNet."
  value       = azurerm_network_interface.vm.private_ip_address
}

output "public_ip_address" {
  description = "Null unless assign_public_ip was set, which it should not normally be."
  value       = var.assign_public_ip ? azurerm_public_ip.vm[0].ip_address : null
}

output "identity_principal_id" {
  description = "Managed identity granted Key Vault Secrets User."
  value       = azurerm_user_assigned_identity.vm.principal_id
}

output "identity_client_id" {
  description = "Client id the application passes to DefaultAzureCredential."
  value       = azurerm_user_assigned_identity.vm.client_id
}

output "app_url" {
  description = "Internal URL once the Phase-2 service exists."
  value       = "http://${azurerm_network_interface.vm.private_ip_address}:${var.app_port}"
}

output "deploy_command" {
  description = "Runs the deploy script on the VM without needing inbound SSH."
  value = join(" ", [
    "az vm run-command invoke",
    "--resource-group ${var.resource_group_name}",
    "--name ${azurerm_linux_virtual_machine.maintenance.name}",
    "--command-id RunShellScript",
    "--scripts 'sudo -u trd365 /opt/trd365/deploy.sh'",
  ])
}

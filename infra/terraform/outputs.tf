output "vm_name" {
  description = "Name of the maintenance VM, for `az vm run-command` and deploys."
  value       = azurerm_linux_virtual_machine.maintenance.name
}

output "resource_group_name" {
  value = local.resource_group_name
}

output "private_ip_address" {
  description = "The address to reach the application on from inside the VNet."
  value       = azurerm_network_interface.vm.private_ip_address
}

output "public_ip_address" {
  description = "Null unless assign_public_ip was set, which it should not normally be."
  value       = var.assign_public_ip ? azurerm_public_ip.vm[0].ip_address : null
}

output "key_vault_name" {
  description = "Vault holding the database credentials. Pass to the secrets tooling."
  value       = local.key_vault_name
}

output "key_vault_uri" {
  value = local.key_vault_uri
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

output "ssh_key_was_generated" {
  description = "True when Terraform generated the key pair rather than using a supplied one."
  value       = local.generated_ssh_key
}

output "ssh_public_key" {
  description = "The public key placed on the VM."
  value       = local.admin_ssh_public_key
}

output "ssh_private_key_pem" {
  description = <<-EOT
    Generated private key, if any. Prefer fetching it from the Key Vault —
    reading it from here means reading it out of Terraform state.
  EOT
  value       = local.generated_ssh_key ? tls_private_key.admin[0].private_key_openssh : null
  sensitive   = true
}

output "next_steps" {
  description = "What to do once this has applied."
  value       = <<-EOT
    1. Populate the vault (needs Secrets Officer — the deployer identity has it):
         AZURE_KEY_VAULT_NAME=${local.key_vault_name} npm run secrets:push -- --apply

    2. Retrieve the SSH key, if one was generated:
         az keyvault secret show --vault-name ${local.key_vault_name} \
           --name maintenance-vm-ssh-private-key --query value -o tsv > ~/.ssh/trd365
         chmod 600 ~/.ssh/trd365

    3. Deploy the application:
         az vm run-command invoke -g ${local.resource_group_name} \
           -n ${azurerm_linux_virtual_machine.maintenance.name} \
           --command-id RunShellScript --scripts 'sudo -u trd365 /opt/trd365/deploy.sh'

    4. Prove the VM can actually reach the databases:
         az vm run-command invoke -g ${local.resource_group_name} \
           -n ${azurerm_linux_virtual_machine.maintenance.name} \
           --command-id RunShellScript --scripts 'sudo /opt/trd365/verify.sh'
  EOT
}

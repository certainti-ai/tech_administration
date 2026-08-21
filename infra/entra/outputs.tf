# ---------------------------------------------------------------------------
# What the VM deployment needs, and what a person needs to check.
# ---------------------------------------------------------------------------

output "client_id" {
  description = "Application (client) ID. This is `entra_client_id` in the VM's tfvars."
  value       = azuread_application.console.client_id
}

output "tenant_id" {
  description = "Tenant. This is `entra_tenant_id` in the VM's tfvars."
  value       = var.tenant_id
}

output "redirect_uri" {
  description = <<-EOT
    The one registered redirect URI. Worth reading back: if this is not exactly
    what the browser arrives at, sign-in fails with AADSTS50011 and no
    server-side trace.
  EOT
  value       = one(tolist(one(azuread_application.console.web).redirect_uris))
}

output "service_principal_object_id" {
  description = "Enterprise application object id — what you assign users and groups to."
  value       = azuread_service_principal.console.object_id
}

output "assignment_required" {
  description = <<-EOT
    True means an unassigned account cannot sign in at all: Entra stops it with
    AADSTS50105 before the application is reached. This is the answer to "not
    everyone with a certainti.ai id should get in", so it is surfaced rather than
    left to be read out of the plan.
  EOT
  value       = azuread_service_principal.console.app_role_assignment_required
}

output "assigned_groups" {
  description = "Group object ids assigned here, by role. Empty is normal — assign in the portal instead."
  value = {
    for role in ["viewer", "operator", "approver", "admin"] :
    role => [for key, value in local.assignments : value.group if value.role == role]
  }
}

output "client_secret" {
  description = <<-EOT
    The client secret. Written into the vault already unless
    write_secrets_to_vault is false — in which case read it with
    `terraform output -raw client_secret` and store it as somebody holding Key
    Vault Secrets Officer:

      az keyvault secret set --vault-name <vault> \
        --name entra-client-secret --value "$(terraform output -raw client_secret)"
  EOT
  value       = azuread_application_password.console.value
  sensitive   = true
}

output "session_signing_secret" {
  description = "Signs session cookies. Same handling as client_secret; the name is session-signing-secret."
  value       = random_password.session.result
  sensitive   = true
}

output "next_steps" {
  description = "What to do with the above."
  value       = <<-EOT
    Put these in infra/terraform/terraform.tfvars and apply:

      entra_tenant_id = "${var.tenant_id}"
      entra_client_id = "${azuread_application.console.client_id}"
      public_hostname = "${var.public_hostname}"

    Then assign somebody. Entra admin centre -> Enterprise applications ->
    ${var.display_name} -> Users and groups -> Add user/group, picking a role.
    Until then nobody can sign in, including whoever applied this.

    Check it with:  curl -s https://${var.public_hostname}/api | jq .authentication
    which should answer "entra id".
  EOT
}

terraform {
  required_version = ">= 1.6"
  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Same storage account as the maintenance deployment, a different key. The
  # state holds the client secret, so it belongs somewhere with the same
  # protection as the state that already holds the SSH private key — not on
  # whichever laptop happened to run the apply.
  #
  #   terraform init \
  #     -backend-config="resource_group_name=trd365-tfstate" \
  #     -backend-config="storage_account_name=trd365tfstated82a2003" \
  #     -backend-config="container_name=tfstate" \
  #     -backend-config="key=entra-app.tfstate"
  backend "azurerm" {}
}

provider "azuread" {
  tenant_id = var.tenant_id
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

data "azuread_client_config" "current" {}

# The vault by name rather than by resource id, because the name is the thing
# anybody involved already knows and a mistyped resource id fails obscurely.
data "azurerm_key_vault" "maintenance" {
  name                = var.key_vault_name
  resource_group_name = var.key_vault_resource_group_name
}

# ---------------------------------------------------------------------------
# the app registration
# ---------------------------------------------------------------------------

resource "azuread_application" "console" {
  display_name = var.display_name

  # One tenant. The application checks the `tid` claim and would refuse another
  # tenant's token anyway, but a registration that cannot be used from elsewhere
  # is a smaller thing to get wrong than one that can and is checked.
  sign_in_audience = "AzureADMyOrg"

  owners = [data.azuread_client_config.current.object_id]

  web {
    redirect_uris = ["https://${var.public_hostname}/auth/callback"]

    implicit_grant {
      # Neither. The application uses the authorization-code flow and reads the
      # ID token server-side; a token in a URL fragment is a token in browser
      # history and in every referrer header.
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  # openid, profile and email — enough to know who someone is, and nothing more.
  # No Graph permission is requested at all, which is why this registration needs
  # no admin consent for anything beyond itself.
  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph

    dynamic "resource_access" {
      for_each = {
        openid  = "37f7f235-527c-4136-accd-4a02d197296e"
        profile = "14dad69e-099b-42c9-810b-d002981feec1"
        email   = "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0"
      }
      content {
        id   = resource_access.value
        type = "Scope"
      }
    }
  }

  # The four roles the application reads. `value` is the contract — the service
  # matches on it exactly — so these strings are not cosmetic.
  #
  # Ordering note: each needs a stable UUID. They are fixed here rather than
  # generated, so re-applying does not delete and recreate the roles and drop
  # everybody's assignment with them.
  app_role {
    id                   = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e01"
    allowed_member_types = ["User"]
    display_name         = "Viewer"
    value                = "viewer"
    description          = "Read environments, utilities, the data model, jobs and the audit trail. Cannot start anything."
    enabled              = true
  }

  app_role {
    id                   = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e02"
    allowed_member_types = ["User"]
    display_name         = "Operator"
    value                = "operator"
    description          = "Start utility runs. Production writes still require a second person to approve."
    enabled              = true
  }

  app_role {
    id                   = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e03"
    allowed_member_types = ["User"]
    display_name         = "Approver"
    value                = "approver"
    description          = "Approve or reject another person's production run. Self-approval is always refused."
    enabled              = true
  }

  app_role {
    id                   = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e04"
    allowed_member_types = ["User"]
    display_name         = "Administrator"
    value                = "admin"
    description          = "Operator and approver together. The one combination that lets one person complete a production deletion alone — assign sparingly."
    enabled              = true
  }
}

resource "azuread_service_principal" "console" {
  client_id = azuread_application.console.client_id
  owners    = [data.azuread_client_config.current.object_id]

  # The answer to "I don't want everyone with a certainti.ai id to get in".
  # With this on, an unassigned person is stopped by Entra with AADSTS50105
  # before the application is ever reached. The application refuses them a second
  # time if they arrive anyway, because the two are maintained by different people.
  app_role_assignment_required = true

  feature_tags {
    enterprise = true
  }
}

# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------

resource "azuread_application_password" "console" {
  application_id = azuread_application.console.id
  display_name   = "maintenance-vm"
  end_date       = timeadd(timestamp(), "${var.secret_valid_days * 24}h")

  lifecycle {
    # Otherwise every plan wants to rotate it, because end_date is computed from
    # the current time. Rotate deliberately with -replace.
    ignore_changes = [end_date]
  }
}

# Signs session cookies. Not a password anyone types, and not derived from
# anything — 32 random bytes held only in state and the vault.
resource "random_password" "session" {
  length  = 48
  special = false
}

# The two names the service reads. They are not configurable here on purpose:
# the VM looks for exactly these, and a vault holding a correct secret under a
# different name looks identical to a vault holding nothing.
resource "azurerm_key_vault_secret" "client_secret" {
  count = var.write_secrets_to_vault ? 1 : 0

  name         = "entra-client-secret"
  value        = azuread_application_password.console.value
  key_vault_id = data.azurerm_key_vault.maintenance.id
}

resource "azurerm_key_vault_secret" "session" {
  count = var.write_secrets_to_vault ? 1 : 0

  name         = "session-signing-secret"
  value        = random_password.session.result
  key_vault_id = data.azurerm_key_vault.maintenance.id
}

# ---------------------------------------------------------------------------
# assignments — only what was asked for
# ---------------------------------------------------------------------------

# Who gets which role is a decision about the organisation, so nothing is assumed.
# Left empty, `app_role_assignment_required` above means nobody gets in until
# somebody is assigned, in the portal or here.

locals {
  assignments = merge(
    { for id in var.viewer_group_ids : "viewer-${id}" => { group = id, role = "viewer" } },
    { for id in var.operator_group_ids : "operator-${id}" => { group = id, role = "operator" } },
    { for id in var.approver_group_ids : "approver-${id}" => { group = id, role = "approver" } },
    { for id in var.admin_group_ids : "admin-${id}" => { group = id, role = "admin" } },
  )

  role_ids = {
    viewer   = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e01"
    operator = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e02"
    approver = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e03"
    admin    = "6f0a1c8a-1f7e-4a4a-9f0f-2b1a5c3d4e04"
  }
}

resource "azuread_app_role_assignment" "groups" {
  for_each = local.assignments

  app_role_id         = local.role_ids[each.value.role]
  principal_object_id = each.value.group
  resource_object_id  = azuread_service_principal.console.object_id
}

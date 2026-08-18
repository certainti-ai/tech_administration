terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # State must not live on a laptop. This configuration creates the Key Vault
  # and can generate the VM's SSH private key, so the state file is itself
  # sensitive material — see SECURITY.md. Values are supplied with
  # `terraform init -backend-config=...` so nothing environment-specific is
  # committed here.
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      # Do not let `terraform destroy` purge a soft-deleted vault. Soft delete
      # is the recovery window for a vault holding production credentials, and
      # purging on destroy would throw it away.
      purge_soft_delete_on_destroy          = false
      purge_soft_deleted_secrets_on_destroy = false
      recover_soft_deleted_key_vaults       = true
    }
  }

  # Credentials come from ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID /
  # ARM_SUBSCRIPTION_ID in the environment, or from a managed identity in CI.
  subscription_id = var.subscription_id
}

# Identity Terraform is running as. Used to grant the deployer write access to
# the vault it creates, so `secrets:push` can populate it afterwards.
data "azurerm_client_config" "current" {}

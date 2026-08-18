terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # State must not live on a laptop: this VM has Key Vault access and its state
  # records identity and role assignments. Configure a remote backend before the
  # first apply — values are supplied with `terraform init -backend-config=...`
  # so nothing environment-specific is committed here.
  backend "azurerm" {}
}

provider "azurerm" {
  features {}

  # Credentials come from ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID /
  # ARM_SUBSCRIPTION_ID in the environment, or from a managed identity in CI.
  # Never hardcode them here.
  subscription_id = var.subscription_id
}

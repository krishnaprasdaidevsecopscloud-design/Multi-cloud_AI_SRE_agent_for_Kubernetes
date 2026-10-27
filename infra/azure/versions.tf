terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
  }

  # Production: uncomment and use your own storage account for remote state.
  # backend "azurerm" {
  #   resource_group_name  = "tfstate-rg"
  #   storage_account_name = "mytfstate"
  #   container_name       = "tfstate"
  #   key                  = "sre-agent/azure.tfstate"
  # }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# The helm provider talks to AKS only when enable_aks = true.
provider "helm" {
  kubernetes {
    host                   = try(data.azurerm_kubernetes_cluster.this.kube_config[0].host, "")
    cluster_ca_certificate = try(base64decode(data.azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate), "")
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "kubelogin"
      args        = ["get-token", "--login", "azurecli", "--server-id", "6dae42f8-4368-4678-94ff-3960e28e3630"]
    }
  }
}

data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

data "azurerm_kubernetes_cluster" "this" {
  name                = var.aks_cluster_name
  resource_group_name = var.aks_resource_group_name
}

locals {
  tags = merge({ Project = "multi-cloud-ai-sre-agent", ManagedBy = "terraform" }, var.tags)

  openai_endpoint = var.create_openai ? azurerm_cognitive_account.openai[0].endpoint : var.existing_openai_endpoint
  openai_scope    = var.create_openai ? azurerm_cognitive_account.openai[0].id : var.existing_openai_account_id

  agent_env = {
    SRE_PROVIDER                = "azure_openai"
    SRE_AZURE_OPENAI_ENDPOINT   = local.openai_endpoint
    SRE_AZURE_OPENAI_DEPLOYMENT = var.openai_model_name
    SRE_ALLOWED_NAMESPACES      = var.allowed_namespaces
  }
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

# ---------------------------------------------------------------- Azure OpenAI
resource "azurerm_cognitive_account" "openai" {
  count                         = var.create_openai ? 1 : 0
  name                          = "${var.name}-oai-${random_string.suffix.result}"
  location                      = var.location
  resource_group_name           = data.azurerm_resource_group.this.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "${var.name}-oai-${random_string.suffix.result}"
  local_auth_enabled            = false # keyless: Entra ID only, no API keys to leak
  public_network_access_enabled = true  # tighten with private endpoints for production
  tags                          = local.tags
}

resource "azurerm_cognitive_deployment" "model" {
  count                = var.create_openai ? 1 : 0
  name                 = var.openai_model_name # deployment name the app uses
  cognitive_account_id = azurerm_cognitive_account.openai[0].id

  model {
    format  = "OpenAI"
    name    = var.openai_model_name
    version = var.openai_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.openai_capacity_k_tpm
  }
}

# ---------------------------------------------------------------- ACR
resource "azurerm_container_registry" "this" {
  name                = "${var.name}acr${random_string.suffix.result}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = local.tags
}

# ---------------------------------------------------------------- identity + roles
resource "azurerm_user_assigned_identity" "agent" {
  name                = "${var.name}-id"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "openai_user" {
  scope                = local.openai_scope
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

# Remote access (Container Apps -> AKS): read-only Kubernetes data-plane via Azure RBAC.
resource "azurerm_role_assignment" "aks_cluster_user" {
  count                = var.enable_container_apps ? 1 : 0
  scope                = data.azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

resource "azurerm_role_assignment" "aks_rbac_reader" {
  count                = var.enable_container_apps ? 1 : 0
  scope                = data.azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Reader"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

resource "azurerm_log_analytics_workspace" "this" {
  count               = var.enable_container_apps ? 1 : 0
  name                = "${var.name}-logs"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  count                      = var.enable_container_apps ? 1 : 0
  name                       = "${var.name}-env"
  location                   = var.location
  resource_group_name        = data.azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this[0].id
  tags                       = local.tags
}

resource "azurerm_container_app" "agent" {
  count                        = var.enable_container_apps ? 1 : 0
  name                         = var.name
  container_app_environment_id = azurerm_container_app_environment.this[0].id
  resource_group_name          = data.azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent.id]
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.agent.id
  }

  ingress {
    external_enabled = false # reachable only inside the environment/VNet
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "agent"
      image  = "${azurerm_container_registry.this.login_server}/${var.name}:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = merge(local.agent_env, {
          SRE_CLUSTER_TYPE     = "aks"
          SRE_CLUSTER_ENDPOINT = "https://${data.azurerm_kubernetes_cluster.this.fqdn}:443"
          SRE_CLUSTER_CA_DATA  = try(data.azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate, "")
          AZURE_CLIENT_ID      = azurerm_user_assigned_identity.agent.client_id # selects the managed identity
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8080
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

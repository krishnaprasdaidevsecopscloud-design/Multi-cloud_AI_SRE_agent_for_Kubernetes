# Agent running INSIDE AKS: Entra Workload Identity (federated credential) gives the pod an
# Azure token with no secrets; the Helm ClusterRole gives it read-only Kubernetes access.
resource "azurerm_federated_identity_credential" "aks" {
  count               = var.enable_aks ? 1 : 0
  name                = "${var.name}-aks"
  resource_group_name = data.azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.agent.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = data.azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:${var.k8s_namespace}:${var.name}"
}

# kubelet must be able to pull from ACR
resource "azurerm_role_assignment" "kubelet_acr_pull" {
  count                = var.enable_aks ? 1 : 0
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = data.azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

resource "helm_release" "agent" {
  count            = var.enable_aks ? 1 : 0
  name             = var.name
  chart            = "${path.module}/../../deploy/helm/sre-agent"
  namespace        = var.k8s_namespace
  create_namespace = true
  atomic           = true
  timeout          = 300

  set {
    name  = "image.repository"
    value = "${azurerm_container_registry.this.login_server}/${var.name}"
  }
  set {
    name  = "image.tag"
    value = var.image_tag
  }
  set {
    name  = "provider"
    value = "azure_openai"
  }
  set {
    name  = "serviceAccount.name"
    value = var.name
  }
  set {
    name  = "serviceAccount.annotations.azure\\.workload\\.identity/client-id"
    value = azurerm_user_assigned_identity.agent.client_id
  }
  set {
    name  = "podLabels.azure\\.workload\\.identity/use"
    value = "true"
    type  = "string"
  }
  set {
    name  = "allowedNamespaces"
    value = var.allowed_namespaces
  }
  set {
    name  = "env.SRE_AZURE_OPENAI_ENDPOINT"
    value = local.openai_endpoint
  }
  set {
    name  = "env.SRE_AZURE_OPENAI_DEPLOYMENT"
    value = var.openai_model_name
  }

  depends_on = [azurerm_federated_identity_credential.aks, azurerm_role_assignment.kubelet_acr_pull]
}

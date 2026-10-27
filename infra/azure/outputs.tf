output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "openai_endpoint" {
  value = local.openai_endpoint
}

output "identity_client_id" {
  value = azurerm_user_assigned_identity.agent.client_id
}

output "container_app_fqdn" {
  value = try(azurerm_container_app.agent[0].ingress[0].fqdn, null)
}

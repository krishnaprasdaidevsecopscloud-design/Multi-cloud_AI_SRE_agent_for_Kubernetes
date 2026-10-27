variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "name" {
  description = "Base name; must be lowercase alphanumeric/hyphen."
  type        = string
  default     = "sreagent"
}

variable "resource_group_name" {
  description = "Existing resource group for the new resources."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "image_tag" {
  type    = string
  default = "0.1.0"
}

# ---- Azure OpenAI ----
variable "create_openai" {
  description = "Create the Azure OpenAI account + model deployment. Set false to reuse one."
  type        = bool
  default     = true
}

variable "openai_model_name" {
  type    = string
  default = "gpt-4o"
}

variable "openai_model_version" {
  type    = string
  default = "2024-11-20"
}

variable "openai_capacity_k_tpm" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 30
}

variable "existing_openai_endpoint" {
  description = "Used when create_openai = false."
  type        = string
  default     = ""
}

variable "existing_openai_account_id" {
  description = "Resource ID of the existing account (for role assignment) when create_openai = false."
  type        = string
  default     = ""
}

# ---- AKS ----
variable "aks_cluster_name" {
  description = "Existing AKS cluster to investigate / deploy into. AKS needs: OIDC issuer + workload identity enabled, Entra ID integration with Azure RBAC."
  type        = string
}

variable "aks_resource_group_name" {
  type = string
}

variable "allowed_namespaces" {
  type    = string
  default = ""
}

variable "k8s_namespace" {
  type    = string
  default = "sre-agent"
}

# ---- targets ----
variable "enable_container_apps" {
  type    = bool
  default = false
}

variable "enable_aks" {
  description = "Run the agent inside AKS via Helm + workload identity."
  type        = bool
  default     = false
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "sre-agent"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "image_tag" {
  description = "Tag of the image already pushed to the ECR repo created by this stack."
  type        = string
  default     = "0.1.0"
}

variable "bedrock_model_id" {
  description = "Bedrock model or cross-region inference profile ID."
  type        = string
  default     = "us.amazon.nova-pro-v1:0"
}

variable "eks_cluster_name" {
  description = "Existing EKS cluster to investigate (and to deploy into when enable_eks = true)."
  type        = string
}

variable "allowed_namespaces" {
  description = "Comma-separated namespace allow-list for the agent; empty = all."
  type        = string
  default     = ""
}

# ---- deployment targets (turn on what you need) ----
variable "enable_agentcore" {
  type    = bool
  default = false
}

variable "enable_ecs" {
  type    = bool
  default = false
}

variable "enable_eks" {
  description = "Run the agent inside EKS via Helm + EKS Pod Identity."
  type        = bool
  default     = false
}

# ---- ECS Fargate networking ----
variable "private_subnet_ids" {
  description = "Private subnets with NAT/VPC endpoints (needs egress to Bedrock, STS, EKS API)."
  type        = list(string)
  default     = []
}

variable "vpc_id" {
  type    = string
  default = ""
}

# ---- EKS in-cluster deployment ----
variable "k8s_namespace" {
  type    = string
  default = "sre-agent"
}

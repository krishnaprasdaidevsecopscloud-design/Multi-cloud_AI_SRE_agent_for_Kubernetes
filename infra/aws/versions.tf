terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.18.0" # aws_bedrockagentcore_agent_runtime needs a recent 6.x
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
  }

  # Production: uncomment and point at your own state bucket (S3 + DynamoDB/lockfile).
  # backend "s3" {
  #   bucket       = "my-tfstate"
  #   key          = "sre-agent/aws.tfstate"
  #   region       = "us-east-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = merge({ Project = "multi-cloud-ai-sre-agent", ManagedBy = "terraform" }, var.tags)
  }
}

# The helm provider talks to EKS only when enable_eks = true.
provider "helm" {
  kubernetes {
    host                   = try(data.aws_eks_cluster.this[0].endpoint, "")
    cluster_ca_certificate = try(base64decode(data.aws_eks_cluster.this[0].certificate_authority[0].data), "")
    token                  = try(data.aws_eks_cluster_auth.this[0].token, "")
  }
}

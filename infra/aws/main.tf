data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  # Nova via a cross-region inference profile can be served from several regions, so the
  # underlying foundation-model ARN must be allowed in any region; the profile ARN is pinned.
  model_base = trimprefix(trimprefix(trimprefix(var.bedrock_model_id, "us."), "eu."), "apac.")
  bedrock_resources = [
    "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/${local.model_base}",
    "arn:${data.aws_partition.current.partition}:bedrock:${var.region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
  ]
  need_eks_data = var.enable_eks || var.enable_ecs || var.enable_agentcore

  agent_env = {
    SRE_PROVIDER         = "bedrock"
    SRE_AWS_REGION       = var.region
    SRE_BEDROCK_MODEL_ID = var.bedrock_model_id
    SRE_CLUSTER_TYPE     = "eks"
    SRE_CLUSTER_NAME     = var.eks_cluster_name
    # endpoint/CA are filled in by each target from the data source below
    SRE_ALLOWED_NAMESPACES = var.allowed_namespaces
  }
}

data "aws_eks_cluster" "this" {
  count = local.need_eks_data ? 1 : 0
  name  = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "this" {
  count = var.enable_eks ? 1 : 0
  name  = var.eks_cluster_name
}

# ---------------------------------------------------------------- ECR
resource "aws_ecr_repository" "agent" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------- shared permissions
# Least privilege: invoke ONE model, describe ONE cluster. Nothing else.
data "aws_iam_policy_document" "agent_permissions" {
  statement {
    sid       = "InvokeNova"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = local.bedrock_resources
  }
  statement {
    sid       = "EcsExecChannel"
    actions   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
    resources = ["*"]
  }
  statement {
    sid       = "DescribeTargetCluster"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:${data.aws_partition.current.partition}:eks:${var.region}:${local.account_id}:cluster/${var.eks_cluster_name}"]
  }
}

resource "aws_iam_policy" "agent" {
  name   = "${var.name}-permissions"
  policy = data.aws_iam_policy_document.agent_permissions.json
}

# Grants the agent role READ-ONLY Kubernetes access on a remote EKS cluster (ECS/AgentCore).
resource "aws_eks_access_entry" "remote" {
  for_each      = var.enable_ecs || var.enable_agentcore ? local.remote_roles : {}
  cluster_name  = var.eks_cluster_name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "remote" {
  for_each      = aws_eks_access_entry.remote
  cluster_name  = var.eks_cluster_name
  principal_arn = each.value.principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
  access_scope {
    type = "cluster"
  }
}

locals {
  remote_roles = merge(
    var.enable_ecs ? { ecs = aws_iam_role.ecs_task[0].arn } : {},
    var.enable_agentcore ? { agentcore = aws_iam_role.agentcore[0].arn } : {},
  )
}

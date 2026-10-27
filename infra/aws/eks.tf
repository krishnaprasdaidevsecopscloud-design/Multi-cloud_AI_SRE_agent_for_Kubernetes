# Agent running INSIDE EKS: EKS Pod Identity gives the pod its AWS credentials (no keys),
# and the Helm chart's ClusterRole gives it read-only Kubernetes access.
data "aws_iam_policy_document" "pod_identity_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pod" {
  count              = var.enable_eks ? 1 : 0
  name               = "${var.name}-pod"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
}

resource "aws_iam_role_policy_attachment" "pod" {
  count      = var.enable_eks ? 1 : 0
  role       = aws_iam_role.pod[0].name
  policy_arn = aws_iam_policy.agent.arn
}

resource "aws_eks_pod_identity_association" "this" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = var.eks_cluster_name
  namespace       = var.k8s_namespace
  service_account = var.name
  role_arn        = aws_iam_role.pod[0].arn
}

resource "helm_release" "agent" {
  count            = var.enable_eks ? 1 : 0
  name             = var.name
  chart            = "${path.module}/../../deploy/helm/sre-agent"
  namespace        = var.k8s_namespace
  create_namespace = true
  atomic           = true
  timeout          = 300

  set {
    name  = "image.repository"
    value = aws_ecr_repository.agent.repository_url
  }
  set {
    name  = "image.tag"
    value = var.image_tag
  }
  set {
    name  = "provider"
    value = "bedrock"
  }
  set {
    name  = "serviceAccount.name"
    value = var.name
  }
  set {
    name  = "allowedNamespaces"
    value = var.allowed_namespaces
  }
  set {
    name  = "env.SRE_AWS_REGION"
    value = var.region
  }
  set {
    name  = "env.SRE_BEDROCK_MODEL_ID"
    value = var.bedrock_model_id
  }

  depends_on = [aws_eks_pod_identity_association.this]
}

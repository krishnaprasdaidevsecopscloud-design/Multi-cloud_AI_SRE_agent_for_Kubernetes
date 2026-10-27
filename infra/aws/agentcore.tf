data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "agentcore" {
  count              = var.enable_agentcore ? 1 : 0
  name               = "${var.name}-agentcore"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
}

resource "aws_iam_role_policy_attachment" "agentcore" {
  count      = var.enable_agentcore ? 1 : 0
  role       = aws_iam_role.agentcore[0].name
  policy_arn = aws_iam_policy.agent.arn
}

# AgentCore pulls the image from ECR and writes logs/traces.
data "aws_iam_policy_document" "agentcore_runtime" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.agent.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${var.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agentcore_runtime" {
  count  = var.enable_agentcore ? 1 : 0
  name   = "runtime"
  role   = aws_iam_role.agentcore[0].id
  policy = data.aws_iam_policy_document.agentcore_runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "this" {
  count              = var.enable_agentcore ? 1 : 0
  agent_runtime_name = replace(var.name, "-", "_") # AgentCore names allow [a-zA-Z0-9_] only
  description        = "Read-only multi-cloud AI SRE investigation agent"
  role_arn           = aws_iam_role.agentcore[0].arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  environment_variables = merge(local.agent_env, {
    SRE_CLUSTER_ENDPOINT = try(data.aws_eks_cluster.this[0].endpoint, "")
    SRE_CLUSTER_CA_DATA  = try(data.aws_eks_cluster.this[0].certificate_authority[0].data, "")
  })

  depends_on = [aws_iam_role_policy.agentcore_runtime]
}

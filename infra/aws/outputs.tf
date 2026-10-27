output "ecr_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

output "agentcore_runtime_arn" {
  value = try(aws_bedrockagentcore_agent_runtime.this[0].agent_runtime_arn, null)
}

output "ecs_cluster" {
  value = try(aws_ecs_cluster.this[0].name, null)
}

output "eks_pod_role_arn" {
  value = try(aws_iam_role.pod[0].arn, null)
}

resource "aws_cloudwatch_log_group" "ecs" {
  count             = var.enable_ecs ? 1 : 0
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  count              = var.enable_ecs ? 1 : 0
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  count      = var.enable_ecs ? 1 : 0
  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  count              = var.enable_ecs ? 1 : 0
  name               = "${var.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task" {
  count      = var.enable_ecs ? 1 : 0
  role       = aws_iam_role.ecs_task[0].name
  policy_arn = aws_iam_policy.agent.arn
}

resource "aws_ecs_cluster" "this" {
  count = var.enable_ecs ? 1 : 0
  name  = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_security_group" "ecs" {
  count       = var.enable_ecs ? 1 : 0
  name        = "${var.name}-ecs"
  description = "SRE agent tasks: no inbound from the internet, HTTPS egress only"
  vpc_id      = var.vpc_id

  egress {
    description = "HTTPS to Bedrock, STS, EKS API"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "this" {
  count                    = var.enable_ecs ? 1 : 0
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution[0].arn
  task_role_arn            = aws_iam_role.ecs_task[0].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name                   = "agent"
    image                  = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = false # the kubernetes client writes a CA temp file
    portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
    environment = [for k, v in merge(local.agent_env, {
      SRE_CLUSTER_ENDPOINT = try(data.aws_eks_cluster.this[0].endpoint, "")
      SRE_CLUSTER_CA_DATA  = try(data.aws_eks_cluster.this[0].certificate_authority[0].data, "")
    }) : { name = k, value = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ecs[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "agent"
      }
    }
  }])
}

resource "aws_ecs_service" "this" {
  count           = var.enable_ecs ? 1 : 0
  name            = var.name
  cluster         = aws_ecs_cluster.this[0].id
  task_definition = aws_ecs_task_definition.this[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  enable_execute_command = true # smoke-test via `aws ecs execute-command`; no inbound port needed

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs[0].id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# infra/components/03-application/main.tf


locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# -----------------------------------------------------------------------------
# DEV-ONLY: Conditionally create the Mock NiFi Endpoint.
# -----------------------------------------------------------------------------
module "mock_nifi_endpoint" {
  source = "../../modules/mock_nifi_endpoint"

  count = var.environment_name == "dev" ? 1 : 0

  project_name       = var.project_name
  environment_name   = var.environment_name
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  private_subnet_ids = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
}

# -----------------------------------------------------------------------------
# Section 1: IAM Policy & Attachment for the Lambda Function
# -----------------------------------------------------------------------------
resource "aws_iam_policy" "aggregator_lambda_policy" {
  name_prefix = "${var.lambda_function_name}-permissions-"
  description = "Permissions for the data aggregator Lambda function"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Effect   = "Allow"
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.lambda_function_name}:*"
      },
      { Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Effect = "Allow", Resource = data.terraform_remote_state.stateful.outputs.main_queue_arn },
      { Action = "s3:GetObject", Effect = "Allow", Resource = "${data.terraform_remote_state.stateful.outputs.landing_bucket_arn}/*" },
      { Action = ["s3:PutObject"], Effect = "Allow", Resource = "${data.terraform_remote_state.stateful.outputs.archive_bucket_arn}/*" },
      { Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"], Effect = "Allow", Resource = [data.terraform_remote_state.stateful.outputs.idempotency_table_arn, data.terraform_remote_state.stateful.outputs.circuit_breaker_table_arn] },
      { Action = "secretsmanager:GetSecretValue", Effect = "Allow", Resource = data.terraform_remote_state.stateful.outputs.nifi_secret_arn },
      { Action = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"], Effect = "Allow", Resource = "*" }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "aggregator_lambda_attach" {
  role       = data.terraform_remote_state.stateful.outputs.lambda_iam_role_name
  policy_arn = aws_iam_policy.aggregator_lambda_policy.arn
}

# -----------------------------------------------------------------------------
# Section 2: Lambda Security Group & Rules
# -----------------------------------------------------------------------------
resource "aws_security_group" "aggregator_lambda_sg" {
  name        = "${var.lambda_function_name}-sg"
  description = "Controls network access for the aggregator Lambda"
  vpc_id      = data.terraform_remote_state.network.outputs.vpc_id
  tags        = local.common_tags

  # Egress for DEV: Allow HTTPS to anywhere inside the VPC. This is safe and breaks the cycle.
  # Egress for PROD: Allow HTTPS only to the specific on-premise NiFi CIDR.
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    description = "Allow HTTPS to the NiFi endpoint"
    cidr_blocks = var.environment_name == "dev" ? [data.terraform_remote_state.network.outputs.vpc_cidr_block] : [var.nifi_endpoint_cidr]
  }
}

# -----------------------------------------------------------------------------
# Section 3: The Lambda Function Resource
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "aggregator" {
  function_name = var.lambda_function_name
  role          = data.terraform_remote_state.stateful.outputs.lambda_iam_role_arn
  handler       = var.lambda_handler
  runtime       = var.lambda_runtime
  architectures = ["arm64"]
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size
  s3_bucket     = data.terraform_remote_state.stateful.outputs.archive_bucket_id
  s3_key        = var.lambda_s3_key

  ephemeral_storage {
    size = var.lambda_ephemeral_storage_size
  }

  vpc_config {
    subnet_ids         = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
    security_group_ids = [aws_security_group.aggregator_lambda_sg.id]
  }

  environment {
    variables = {
      ARCHIVE_BUCKET_NAME               = data.terraform_remote_state.stateful.outputs.archive_bucket_id
      IDEMPOTENCY_TABLE_NAME            = data.terraform_remote_state.stateful.outputs.idempotency_table_name
      CIRCUIT_BREAKER_TABLE_NAME        = data.terraform_remote_state.stateful.outputs.circuit_breaker_table_name
      NIFI_SECRET_ARN                   = data.terraform_remote_state.stateful.outputs.nifi_secret_arn
      NIFI_ENDPOINT_URL                 = var.environment_name == "dev" ? "https://${module.mock_nifi_endpoint[0].endpoint_dns_name}" : var.nifi_endpoint_url
      LOG_LEVEL                         = "INFO"
      DYNAMODB_TTL_ATTRIBUTE            = "ttl"
      IDEMPOTENCY_TTL_DAYS              = var.idempotency_ttl_days
      NIFI_CONNECT_TIMEOUT_SECONDS      = var.nifi_connect_timeout_seconds
      CIRCUIT_BREAKER_FAILURE_THRESHOLD = var.circuit_breaker_failure_threshold
      CIRCUIT_BREAKER_OPEN_SECONDS      = var.circuit_breaker_open_seconds
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Section 4: The SQS Trigger
# -----------------------------------------------------------------------------
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn                   = data.terraform_remote_state.stateful.outputs.main_queue_arn
  function_name                      = aws_lambda_function.aggregator.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
}
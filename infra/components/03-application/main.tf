# infra/components/03-application/main.tf


locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
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
        Resource = "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.lambda_function_name}:*"
      },
      {
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Effect   = "Allow"
        Resource = data.terraform_remote_state.stateful.outputs.main_queue_arn
      },
      {
        Action   = "s3:GetObject"
        Effect   = "Allow"
        Resource = "${data.terraform_remote_state.stateful.outputs.landing_bucket_arn}/*"
      },
      {
        Action = ["s3:PutObject"]
        Effect = "Allow"
        Resource = [
          "${data.terraform_remote_state.stateful.outputs.archive_bucket_arn}/*",
          "${data.terraform_remote_state.stateful.outputs.distribution_bucket_arn}/*" # Added permission
        ]
      },
      {
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Effect   = "Allow"
        Resource = data.terraform_remote_state.stateful.outputs.idempotency_table_arn # Simplified
      },
      {
        Action   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "aggregator_lambda_attach" {
  role       = data.terraform_remote_state.stateful.outputs.lambda_iam_role_name
  policy_arn = aws_iam_policy.aggregator_lambda_policy.arn
}


# -----------------------------------------------------------------------------
# Section 2: Lambda Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "aggregator_lambda_sg" {
  name        = "${var.lambda_function_name}-sg"
  description = "Security group for the aggregator Lambda. No egress is required."
  vpc_id      = data.terraform_remote_state.network.outputs.vpc_id
  tags        = local.common_tags
}

# -----------------------------------------------------------------------------
# Section 3: The Lambda Function Resource
# -----------------------------------------------------------------------------

resource "aws_lambda_function" "aggregator" {
  function_name = var.lambda_function_name
  role          = data.terraform_remote_state.stateful.outputs.lambda_iam_role_arn
  handler       = "data_aggregator.app.handler"
  runtime       = var.lambda_runtime
  architectures = ["arm64"]
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size
  s3_bucket     = var.lambda_artifacts_bucket_name
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
      ARCHIVE_BUCKET_NAME      = data.terraform_remote_state.stateful.outputs.archive_bucket_id
      DISTRIBUTION_BUCKET_NAME = data.terraform_remote_state.stateful.outputs.distribution_bucket_id # Added
      IDEMPOTENCY_TABLE_NAME   = data.terraform_remote_state.stateful.outputs.idempotency_table_name
      LOG_LEVEL                = "INFO"
      IDEMPOTENCY_TTL_DAYS     = var.idempotency_ttl_days
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
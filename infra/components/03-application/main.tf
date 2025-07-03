# components/03-application/main.tf

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# --- IAM Role for the Lambda Function ---
# This role defines what the Lambda is allowed to do.
resource "aws_iam_role" "lambda_exec" {
  name = "${var.lambda_function_name}-role"
  tags = local.common_tags

  # This "trust policy" allows the Lambda service to assume this role.
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# --- IAM Policy ---
# This policy defines the specific permissions for our function.
resource "aws_iam_policy" "lambda_permissions" {
  name        = "${var.lambda_function_name}-permissions"
  description = "Permissions for the data aggregator Lambda function"

  # The actual permissions, referencing the resources from our other components.
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      # Permissions to write logs to CloudWatch
      {
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      },
      # Permissions for SQS
      {
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Effect   = "Allow"
        Resource = data.terraform_remote_state.stateful.outputs.main_queue_arn
      },
      # Permissions for S3
      {
        Action   = ["s3:GetObject"]
        Effect   = "Allow"
        Resource = "${data.terraform_remote_state.stateful.outputs.landing_bucket_arn}/*" # Note the /* for objects
      },
      {
        Action   = ["s3:PutObject"]
        Effect   = "Allow"
        Resource = "${data.terraform_remote_state.stateful.outputs.archive_bucket_arn}/*"
      },
      # Permissions for DynamoDB
      {
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Effect   = "Allow"
        Resource = [
          data.terraform_remote_state.stateful.outputs.idempotency_table_arn,
          data.terraform_remote_state.stateful.outputs.circuit_breaker_table_arn
        ]
      },
      # Permissions for VPC Networking (to create network interfaces)
      {
        Action   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
        Effect   = "Allow"
        Resource = "*" # This must be wildcarded as interfaces don't exist yet
      }
    ]
  })
}

# Attach the policy to the role
resource "aws_iam_role_policy_attachment" "lambda_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_permissions.arn
}

# --- The Lambda Function Resource ---
# NOTE: We are using a dummy ZIP file for now. The CI/CD pipeline will
# be responsible for creating and uploading the real one.
resource "aws_lambda_function" "processor" {
  function_name    = var.lambda_function_name
  role             = aws_iam_role.lambda_exec.arn
  handler          = var.lambda_handler
  runtime          = var.lambda_runtime
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  filename         = "dummy.zip" # This is a placeholder
  source_code_hash = filebase64sha256("dummy.zip")

  # VPC configuration to place the Lambda inside our private network
  vpc_config {
    subnet_ids         = data.terraform_remote_state.network.outputs.private_subnet_ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = local.common_tags
}

# --- Lambda Security Group ---
resource "aws_security_group" "lambda_sg" {
  name        = "${var.lambda_function_name}-sg"
  description = "Security group for the aggregator lambda"
  vpc_id      = data.terraform_remote_state.network.outputs.vpc_id

  # By default, all ingress is denied.
  # We only need to define egress to the on-premise NiFi endpoint.
  # For now, we allow all outbound traffic. This can be locked down later.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

# --- Event Source Mapping ---
# This is the trigger that connects the SQS queue to the Lambda.
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn                   = data.terraform_remote_state.stateful.outputs.main_queue_arn
  function_name                      = aws_lambda_function.processor.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 10

  # This enables the partial batch failure reporting feature
  function_response_types            = ["ReportBatchItemFailures"]
}
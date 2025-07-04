# components/03-application/main.tf

# -----------------------------------------------------------------------------
# Data Sources
# These retrieve information from AWS or from other Terraform state files.
# -----------------------------------------------------------------------------

# Read outputs from the 01-network component.
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    key    = "dev/components/01-network.tfstate"
    region = "eu-west-2"
  }
}

# Read outputs from the 02-stateful-resources component.
data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    # This key now correctly points to the stateful resources component.
    key    = "dev/components/02-stateful-resources.tfstate"
    region = "eu-west-2"
  }
}

# Automatically get the current AWS account ID and region for building ARNs.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}


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

  project_name      = var.project_name
  environment_name  = var.environment_name
  vpc_id            = data.terraform_remote_state.network.outputs.vpc_id
  public_subnet_ids = values(data.terraform_remote_state.network.outputs.public_subnet_ids)
}

# -----------------------------------------------------------------------------
# Section 1: IAM Policy & Attachment for the Lambda Function
# Defines the specific permissions for this application component.
# -----------------------------------------------------------------------------
resource "aws_iam_policy" "aggregator_lambda_policy" {
  name        = "${var.lambda_function_name}-permissions"
  description = "Permissions for the data aggregator Lambda function"

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Effect   = "Allow"
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.lambda_function_name}:*"
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
        Action   = ["s3:PutObject", "s3:PutObjectMetadata"]
        Effect   = "Allow"
        Resource = "${data.terraform_remote_state.stateful.outputs.archive_bucket_arn}/*"
      },
      {
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Effect   = "Allow"
        Resource = [
          data.terraform_remote_state.stateful.outputs.idempotency_table_arn,
          data.terraform_remote_state.stateful.outputs.circuit_breaker_table_arn
        ]
      },
      {
        Action   = "secretsmanager:GetSecretValue"
        Effect   = "Allow"
        Resource = data.terraform_remote_state.stateful.outputs.nifi_secret_arn
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
# Section 2: Lambda Security Group & Rules
# The stateful firewall for our function, with environment-specific rules.
# -----------------------------------------------------------------------------
resource "aws_security_group" "aggregator_lambda_sg" {
  name        = "${var.lambda_function_name}-sg"
  description = "Controls network access for the aggregator Lambda"
  vpc_id      = data.terraform_remote_state.network.outputs.vpc_id
  tags        = local.common_tags

  # Egress (outbound) rule is dynamic.
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    description = "Allow HTTPS to the NiFi endpoint"
    # In 'dev', allow traffic to the mock endpoint's security group.
    security_groups = var.environment_name == "dev" ? [module.mock_nifi_endpoint[0].endpoint_security_group_id] : null
    # In 'prod', allow traffic to the on-premise NiFi CIDR.
    cidr_blocks     = var.environment_name != "dev" ? [var.nifi_endpoint_cidr] : null
  }
}

# DEV-ONLY: Rule to allow the Lambda to talk to the mock endpoint's ALB.
resource "aws_security_group_rule" "lambda_to_mock_nifi" {
  count = var.environment_name == "dev" ? 1 : 0

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = module.mock_nifi_endpoint[0].endpoint_security_group_id
  source_security_group_id = aws_security_group.aggregator_lambda_sg.id
  description              = "Allow inbound HTTPS from the Aggregator Lambda"
}

# -----------------------------------------------------------------------------
# Section 3: The Lambda Function Resource
# The core application compute, with environment-specific configuration.
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "aggregator" {
  function_name = var.lambda_function_name
  role          = data.terraform_remote_state.stateful.outputs.lambda_iam_role_arn
  handler       = var.lambda_handler
  runtime       = var.lambda_runtime
  architectures = ["arm64"]
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  # Placeholder for the CI/CD pipeline to update with the real application code.
  filename         = "dummy.zip"
  source_code_hash = filebase64sha256("dummy.zip")

  # Place the Lambda inside our private network for secure egress.
  vpc_config {
    # Using values() to correctly convert the map of subnet IDs into a list.
    subnet_ids         = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
    security_group_ids = [aws_security_group.aggregator_lambda_sg.id]
  }

  # Pass infrastructure configuration to the application code as environment variables.
  environment {
    variables = {
      ARCHIVE_BUCKET_NAME        = data.terraform_remote_state.stateful.outputs.archive_bucket_id
      IDEMPOTENCY_TABLE_NAME     = data.terraform_remote_state.stateful.outputs.idempotency_table_name
      CIRCUIT_BREAKER_TABLE_NAME = data.terraform_remote_state.stateful.outputs.circuit_breaker_table_name
      NIFI_SECRET_ARN            = data.terraform_remote_state.stateful.outputs.nifi_secret_arn
      # The NiFi URL is dynamic: it uses the mock endpoint in 'dev' and the real one otherwise.
      NIFI_ENDPOINT_URL          = var.environment_name == "dev" ? "https://${module.mock_nifi_endpoint[0].endpoint_dns_name}" : var.nifi_endpoint_url
      LOG_LEVEL                  = "INFO"
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Section 4: The SQS Trigger
# This connects the SQS queue to the Lambda, making the architecture event-driven.
# -----------------------------------------------------------------------------
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn                   = data.terraform_remote_state.stateful.outputs.main_queue_arn
  function_name                      = aws_lambda_function.aggregator.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 10
  function_response_types            = ["ReportBatchItemFailures"]
}
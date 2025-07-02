# File: infra/modules/data_pipeline/iam.tf

# Defines the IAM role that the Lambda function will assume.
resource "aws_iam_role" "lambda_exec" {
  name = "${local.resource_prefix}-lambda-exec-role"

  # The trust policy allows the AWS Lambda service to assume this role.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Defines the inline policy that grants the Lambda function necessary permissions.
resource "aws_iam_role_policy" "lambda_exec" {
  name = "lambda-execution-policy"
  role = aws_iam_role.lambda_exec.id

  # This policy grants the minimum required permissions.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Permissions to write logs to CloudWatch.
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        # Permissions to read and delete messages from the SQS queue.
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Effect   = "Allow"
        Resource = aws_sqs_queue.main.arn
      },
      {
        # Permission to read objects from the S3 landing bucket.
        Action = [
          "s3:GetObject"
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.landing_zone.arn}/*" # Note the /* for objects
      },
      {
        # Permission to write to the DynamoDB idempotency table.
        Action = [
          "dynamodb:PutItem"
        ]
        Effect   = "Allow"
        Resource = aws_dynamodb_table.idempotency.arn
      },
      {
        # Permission to read the MinIO credentials from Secrets Manager.
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Effect   = "Allow"
        Resource = var.minio_secret_arn
      }
    ]
  })
}
# File: infra/modules/data_pipeline/main.tf

# Use a local variable to create a consistent naming prefix for all resources.
locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# --- S3 Landing Zone Bucket ---
resource "aws_s3_bucket" "landing_zone" {
  bucket = local.resource_prefix
}

# Standalone resource to manage server-side encryption for the S3 bucket.
resource "aws_s3_bucket_server_side_encryption_configuration" "landing_zone" {
  bucket = aws_s3_bucket.landing_zone.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Standalone resource to manage versioning for the S3 bucket.
resource "aws_s3_bucket_versioning" "landing_zone" {
  bucket = aws_s3_bucket.landing_zone.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Block all public access to the S3 bucket.
resource "aws_s3_bucket_public_access_block" "landing_zone" {
  bucket                  = aws_s3_bucket.landing_zone.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- S3 Bucket Lifecycle Configuration ---
resource "aws_s3_bucket_lifecycle_configuration" "landing_zone" {
  bucket = aws_s3_bucket.landing_zone.id

  rule {
    id     = "archive-rule"
    status = "Enabled"

    # FIX: Add an empty filter block to apply this rule to all objects.
    filter {}

    transition {
      days          = 7
      # FIX: Use the correct enum value "DEEP_ARCHIVE".
      storage_class = "DEEP_ARCHIVE"
    }
  }
}

# --- SQS Queues ---

# Dead-Letter Queue (DLQ) to capture messages that fail processing permanently.
resource "aws_sqs_queue" "dlq" {
  name = "${local.resource_prefix}-dlq"
}

# Main queue that receives notifications from S3.
resource "aws_sqs_queue" "main" {
  name                        = local.resource_prefix
  delay_seconds               = 0
  max_message_size            = 262144   # 256 KB
  message_retention_seconds   = 345600   # 4 days
  receive_wait_time_seconds   = 20       # Enables long polling
  visibility_timeout_seconds  = 300      # 5 minutes, must be > Lambda timeout

  # Link to the DLQ. After 3 failed processing attempts, messages go to the DLQ.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

# --- S3 to SQS Notification ---
# This resource connects the S3 bucket to the SQS queue.
resource "aws_s3_bucket_notification" "s3_events" {
  bucket = aws_s3_bucket.landing_zone.id

  queue {
    queue_arn     = aws_sqs_queue.main.arn
    events        = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_sqs_queue_policy.s3_to_sqs]
}

# SQS Queue Policy to allow S3 to send messages to it.
resource "aws_sqs_queue_policy" "s3_to_sqs" {
  queue_url = aws_sqs_queue.main.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.main.arn
        Condition = {
          ArnEquals = { "aws:SourceArn" = aws_s3_bucket.landing_zone.arn }
        }
      }
    ]
  })
}

# --- DynamoDB Table for Idempotency ---
resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.resource_prefix}-idempotency"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "ObjectID"

  attribute {
    name = "ObjectID"
    type = "S" # String
  }

  ttl {
    attribute_name = "ExpiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}
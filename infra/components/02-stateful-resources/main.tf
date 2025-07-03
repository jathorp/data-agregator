# components/02-stateful-resources/main.tf

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# --- S3 BUCKETS ---
resource "aws_s3_bucket" "landing" {
  bucket = var.landing_bucket_name
  tags   = merge(local.common_tags, { Name = var.landing_bucket_name })
}
resource "aws_s3_bucket_versioning" "landing" {
  bucket = aws_s3_bucket.landing.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_public_access_block" "landing" {
  bucket                  = aws_s3_bucket.landing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule {
    id     = "expire-after-7-days"
    status = "Enabled"

    filter {} # <-- ADD THIS EMPTY BLOCK

    expiration {
      days = 7
    }
  }
}

resource "aws_s3_bucket" "archive" {
  bucket = var.archive_bucket_name
  tags   = merge(local.common_tags, { Name = var.archive_bucket_name })
}
resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "archive-to-deep-archive"
    status = "Enabled"
    transition {
      days          = 30
      storage_class = "DEEP_ARCHIVE"
    }
  }
}

# --- SQS QUEUES ---
resource "aws_sqs_queue" "dlq" {
  name = var.dlq_name
  tags = merge(local.common_tags, { Name = var.dlq_name })
}

resource "aws_sqs_queue" "main" {
  name                       = var.main_queue_name
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = 345600 # 4 days
  visibility_timeout_seconds = 60     # Should be > Lambda timeout

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5 # After 5 failures, move to DLQ
  })

  tags = merge(local.common_tags, { Name = var.main_queue_name })
}

# --- DYNAMODB TABLES ---
resource "aws_dynamodb_table" "idempotency" {
  name         = var.idempotency_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "s3_object_key"

  attribute {
    name = "s3_object_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(local.common_tags, { Name = var.idempotency_table_name })
}

resource "aws_dynamodb_table" "circuit_breaker" {
  name         = var.circuit_breaker_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "state_name"

  attribute {
    name = "state_name"
    type = "S"
  }

  tags = merge(local.common_tags, { Name = var.circuit_breaker_table_name })
}
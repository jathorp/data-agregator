# components/02-stateful-resources/main.tf – **KMS-free** version

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

# ────────────────────────────────────────────────────────────────────────────────
# Lambda execution role (shell only – component 03 will attach policies)
# ────────────────────────────────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec_role" {
  name = var.lambda_role_name
  tags = local.common_tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Action    = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# ────────────────────────────────────────────────────────────────────────────────
# S3 – access-logs, landing, archive (all using S3-managed AES-256)
# ────────────────────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "access_logs" {
  bucket        = "${var.project_name}-access-logs-${random_id.suffix.hex}"
  force_destroy = true
  tags          = merge(local.common_tags, { Purpose = "S3 Access Logs" })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    id     = "expire-logs-after-90-days"
    status = "Enabled"
    filter {}
    expiration { days = 90 }
  }
}

# Landing bucket
resource "aws_s3_bucket" "landing" {
  bucket = "${var.landing_bucket_name}-${random_id.suffix.hex}"
  tags   = merge(local.common_tags, { Name = var.landing_bucket_name })
}

resource "aws_s3_bucket_logging" "landing" {
  bucket        = aws_s3_bucket.landing.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "logs/landing/"
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

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule {
    id     = "expire-and-cleanup"
    status = "Enabled"
    filter {}
    expiration { days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_policy" "landing" {
  bucket = aws_s3_bucket.landing.id
  policy = data.aws_iam_policy_document.enforce_tls_landing.json
}

# Archive bucket
resource "aws_s3_bucket" "archive" {
  bucket = "${var.archive_bucket_name}-${random_id.suffix.hex}"
  lifecycle { prevent_destroy = true }
  tags = merge(local.common_tags, { Name = var.archive_bucket_name })
}

resource "aws_s3_bucket_logging" "archive" {
  bucket        = aws_s3_bucket.archive.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "logs/archive/"
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

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "archive-to-deep-archive-and-cleanup"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "DEEP_ARCHIVE"
    }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
    expiration { expired_object_delete_marker = true }
  }
}

resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id
  policy = data.aws_iam_policy_document.enforce_tls_archive.json
}

# ────────────────────────────────────────────────────────────────────────────────
# SQS – uses AWS-managed encryption (`alias/aws/sqs`)
# ────────────────────────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                    = var.dlq_name
  sqs_managed_sse_enabled = true
  tags                    = merge(local.common_tags, { Name = var.dlq_name })
}

resource "aws_sqs_queue" "main" {
  name                       = var.main_queue_name
  message_retention_seconds  = 345600
  visibility_timeout_seconds = 90
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn,
    maxReceiveCount     = 5
  })
  tags = merge(local.common_tags, { Name = var.main_queue_name })
}

resource "aws_sqs_queue_policy" "s3_to_sqs" {
  queue_url = aws_sqs_queue.main.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Sid       = "AllowS3SendMessage",
      Effect    = "Allow",
      Principal = { Service = "s3.amazonaws.com" },
      Action    = ["SQS:SendMessage"],
      Resource  = aws_sqs_queue.main.arn,
      Condition = {
        ArnEquals    = { "aws:SourceArn" = aws_s3_bucket.landing.arn },
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_s3_bucket_notification" "landing_to_sqs" {
  bucket = aws_s3_bucket.landing.id
  queue {
    queue_arn = aws_sqs_queue.main.arn
    events    = ["s3:ObjectCreated:*"]
  }
  depends_on = [aws_sqs_queue_policy.s3_to_sqs]
}

# ────────────────────────────────────────────────────────────────────────────────
# DynamoDB – encrypted with AWS-owned keys (default)
# ────────────────────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "idempotency" {
  name         = var.idempotency_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "object_key"

  attribute {
    name = "object_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }

  server_side_encryption { enabled = true } # AWS-managed key

  tags = merge(local.common_tags, { Name = var.idempotency_table_name })
  lifecycle { prevent_destroy = true }
}

resource "aws_dynamodb_table" "circuit_breaker" {
  name         = var.circuit_breaker_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "service_name"

  attribute {
    name = "service_name"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled = true
  }

  tags = merge(local.common_tags, { Name = var.circuit_breaker_table_name })
  lifecycle { prevent_destroy = true }
}

# ────────────────────────────────────────────────────────────────────────────────
# Secrets Manager – default AWS-managed key
# ────────────────────────────────────────────────────────────────────────────────
resource "aws_secretsmanager_secret" "nifi_credentials" {
  name = var.nifi_secret_name
  tags = merge(local.common_tags, { Name = var.nifi_secret_name })
}

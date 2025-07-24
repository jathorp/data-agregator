# components/02-stateful-resources/main.tf — KMS-free, stable, clear

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# Lambda Execution Role (policies attached elsewhere)
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

# ──────────────────────────────────────────────────────────────
# S3 Buckets — Deterministic names, KMS-free
# ──────────────────────────────────────────────────────────────

# Access Logs Bucket
resource "aws_s3_bucket" "access_logs" {
  bucket        = "${var.project_name}-s3-access-logs-${var.environment_name}"
  force_destroy = true
  tags          = merge(local.common_tags, { Purpose = "S3 Access Logs" })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
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

# Landing Bucket
resource "aws_s3_bucket" "landing" {
  bucket = var.landing_bucket_name
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

# Archive Bucket
resource "aws_s3_bucket" "archive" {
  bucket = var.archive_bucket_name
  tags   = merge(local.common_tags, { Name = var.archive_bucket_name })

  # lifecycle {
  #   prevent_destroy = True
  # }
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

# Distribution Bucket

resource "aws_s3_bucket" "distribution" {
  bucket = var.distribution_bucket_name
  tags   = merge(local.common_tags, { Name = var.distribution_bucket_name })
}

resource "aws_s3_bucket_versioning" "distribution" {
  bucket = aws_s3_bucket.distribution.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_logging" "distribution" {
  bucket        = aws_s3_bucket.distribution.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "logs/distribution/"
}

resource "aws_s3_bucket_public_access_block" "distribution" {
  bucket                  = aws_s3_bucket.distribution.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "distribution" {
  bucket = aws_s3_bucket.distribution.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "distribution" {
  bucket = aws_s3_bucket.distribution.id
  rule {
    id     = "expire-unprocessed-files"
    status = "Enabled"
    filter {}
    expiration { days = 14 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_policy" "distribution" {
  bucket = aws_s3_bucket.distribution.id
  policy = data.aws_iam_policy_document.enforce_tls_distribution.json
}

# ──────────────────────────────────────────────────────────────
# S3 Replication Configuration (Distribution -> Archive)
# ──────────────────────────────────────────────────────────────

# IAM Role for S3 to assume when replicating objects.
resource "aws_iam_role" "replication" {
  name = "${var.project_name}-${var.environment_name}-s3-replication-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# IAM Policy defining what the replication role is allowed to do.
resource "aws_iam_policy" "replication" {
  name_prefix = "${var.project_name}-${var.environment_name}-s3-replication-policy-"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Allow reading from the source bucket
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetReplicationConfiguration",
          "s3:GetObjectVersionForReplication",
          "s3:GetObjectVersionAcl",
          "s3:GetObjectVersionTagging"
        ]
        Resource = [
          aws_s3_bucket.distribution.arn,
          "${aws_s3_bucket.distribution.arn}/*"
        ]
      },
      {
        # Allow writing to the destination bucket
        Effect = "Allow"
        Action = [
          "s3:ReplicateObject",
          "s3:ReplicateDelete",
          "s3:ReplicateTags"
        ]
        Resource = "${aws_s3_bucket.archive.arn}/*"
      }
    ]
  })
}

# Attach the policy to the role.
resource "aws_iam_role_policy_attachment" "replication" {
  role       = aws_iam_role.replication.name
  policy_arn = aws_iam_policy.replication.arn
}

# The replication configuration itself, attached to the source bucket.
resource "aws_s3_bucket_replication_configuration" "distribution_to_archive" {
  depends_on = [aws_iam_role.replication]

  role   = aws_iam_role.replication.arn
  bucket = aws_s3_bucket.distribution.id

  rule {
    id     = "DistToArchive"
    status = "Enabled"

    filter {} # An empty filter means "replicate everything"

    destination {
      bucket        = aws_s3_bucket.archive.arn
      storage_class = "STANDARD" # Bundles arrive in Standard, then transition via lifecycle.
    }

    # This is the key part: DO NOT replicate delete markers.
    delete_marker_replication {
      status = "Disabled"
    }
  }
}

# ──────────────────────────────────────────────────────────────
# SQS Queues
# ──────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                    = var.dlq_name
  sqs_managed_sse_enabled = true
  tags                    = merge(local.common_tags, { Name = var.dlq_name })
}

resource "aws_sqs_queue" "main" {
  name                       = var.main_queue_name
  message_retention_seconds  = 345600
  visibility_timeout_seconds = 200
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
    queue_arn     = aws_sqs_queue.main.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = var.s3_event_notification_prefix
  }
  depends_on = [aws_sqs_queue_policy.s3_to_sqs]
}

# ──────────────────────────────────────────────────────────────
# DynamoDB Table
# ──────────────────────────────────────────────────────────────
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
  server_side_encryption { enabled = true }

  tags = merge(local.common_tags, { Name = var.idempotency_table_name })

  # lifecycle {
  #   prevent_destroy = True
  # }
}

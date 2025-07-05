# components/02-stateful-resources/main.tf

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

# --- Action 1: Hardened Customer-Managed KMS Key ---
resource "aws_kms_key" "app_key" {
  description             = "KMS key for the ${var.project_name} application resources"
  deletion_window_in_days = 10
  enable_key_rotation     = true
  tags                    = local.common_tags
}

data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev" # Use your actual tfstate bucket name
    key    = "dev/components/00-security.tfstate"
    region = "eu-west-2" # Use your actual region
  }
}

data "aws_iam_policy_document" "kms_policy" {
  # Statement 1: Gives full administrative control to the root user (fail-safe)
  # and the specified infrastructure admin role.
  statement {
    sid       = "EnableIAMUserPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type = "AWS"
      identifiers = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root",
        # Use the output from the security component instead of a variable
        data.terraform_remote_state.security.outputs.kms_admin_role_arn
      ]
    }
  }

  # Statement 2: Gives usage permissions to the application Lambda function's role.
  statement {
    sid    = "AllowLambdaUsage"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = ["*"]
    principals {
      type = "AWS"
      # This reference is now safe because this policy is applied AFTER the role is created.
      identifiers = [aws_iam_role.lambda_exec_role.arn]
    }
  }
}

# NEW resource to attach the policy to the existing key.
# This happens AFTER both the key and the IAM role are created, solving the race condition.
resource "aws_kms_key_policy" "app_key_policy" {
  key_id = aws_kms_key.app_key.id
  policy = data.aws_iam_policy_document.kms_policy.json
}

# --- NEW: IAM Role for the Lambda Function ---
# This role "shell" is created here to break the circular dependency.
# The 03-application component will look up this role and attach policies to it.
resource "aws_iam_role" "lambda_exec_role" {
  name = var.lambda_role_name
  tags = local.common_tags

  # This "trust policy" allows the Lambda service to assume this role.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# --- S3 ACCESS LOGGING BUCKET (Security Recommendation) ---
resource "aws_s3_bucket" "access_logs" {
  bucket = "${var.project_name}-access-logs-${random_id.suffix.hex}"
  tags   = merge(local.common_tags, { Purpose = "S3 Access Logs" })

  # Action 3: Allow easy cleanup in non-prod environments.
  force_destroy = true
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

# --- S3 BUCKET: LANDING ---
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
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.app_key.arn
    }
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
# Action 2: Enforce encryption-in-transit for the landing bucket.
resource "aws_s3_bucket_policy" "landing" {
  bucket = aws_s3_bucket.landing.id
  policy = data.aws_iam_policy_document.enforce_tls_landing.json
}
data "aws_iam_policy_document" "enforce_tls_landing" {
  statement {
    sid     = "EnforceTLSTrafficOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.landing.arn,
      "${aws_s3_bucket.landing.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# --- S3 BUCKET: ARCHIVE ---
resource "aws_s3_bucket" "archive" {
  bucket = "${var.archive_bucket_name}-${random_id.suffix.hex}"
  tags   = merge(local.common_tags, { Name = var.archive_bucket_name })
  lifecycle { prevent_destroy = true }
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
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.app_key.arn
    }
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
# Action 2: Enforce encryption-in-transit for the archive bucket.
resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id
  policy = data.aws_iam_policy_document.enforce_tls_archive.json
}
data "aws_iam_policy_document" "enforce_tls_archive" {
  statement {
    sid     = "EnforceTLSTrafficOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.archive.arn,
      "${aws_s3_bucket.archive.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# --- SQS QUEUES ---
resource "aws_sqs_queue" "dlq" {
  name              = var.dlq_name
  kms_master_key_id = aws_kms_key.app_key.arn # Using CMK
  tags              = merge(local.common_tags, { Name = var.dlq_name })
}
resource "aws_sqs_queue" "main" {
  name                       = var.main_queue_name
  message_retention_seconds  = 345600
  visibility_timeout_seconds = 90
  kms_master_key_id          = aws_kms_key.app_key.arn # Using CMK
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
  tags = merge(local.common_tags, { Name = var.main_queue_name })
}

# --- PIPELINE WIRING: S3 -> SQS ---
resource "aws_s3_bucket_notification" "landing_to_sqs" {
  bucket = aws_s3_bucket.landing.id
  queue {
    queue_arn = aws_sqs_queue.main.arn
    events    = ["s3:ObjectCreated:*"]
  }
  depends_on = [aws_sqs_queue_policy.s3_to_sqs]
}
resource "aws_sqs_queue_policy" "s3_to_sqs" {
  queue_url = aws_sqs_queue.main.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "s3.amazonaws.com" },
      Action    = "SQS:SendMessage",
      Resource  = aws_sqs_queue.main.arn,
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_s3_bucket.landing.arn }
      }
    }]
  })
}

# --- DYNAMODB TABLES ---
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
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app_key.arn
  }
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
  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app_key.arn
  }
  tags = merge(local.common_tags, { Name = var.circuit_breaker_table_name })
  lifecycle { prevent_destroy = true }
}

# --- SECRETS MANAGER ---
resource "aws_secretsmanager_secret" "nifi_credentials" {
  name       = var.nifi_secret_name
  kms_key_id = aws_kms_key.app_key.arn # Encrypt the secret with our CMK
  tags       = merge(local.common_tags, { Name = var.nifi_secret_name })
}
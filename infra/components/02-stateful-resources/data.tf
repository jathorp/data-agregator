# components/02-stateful-resources/data.tf – matches the simplified main.tf

# Define the Terraform state bucket name in one central place for this component.
# This avoids hardcoding the same string in multiple data blocks below.
locals {
  remote_state_bucket = "data-aggregator-tfstate-dev"
}

# --- Data source to read outputs from the '00-security' component ---
data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    # CORRECTED: Use the local variable for the bucket name
    bucket = local.remote_state_bucket

    # CORRECTED: Use the standardized key path structure
    key    = "components/00-security/${var.environment_name}.tfstate"

    # CORRECTED: Use the aws_region variable for consistency
    region = var.aws_region
  }
}

# --- Data sources to get general AWS account information ---
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}


# --- S3 Bucket Policies ---
# These policies enforce TLS encryption in transit for all S3 operations.

# S3 bucket policy to enforce TLS for the landing bucket
data "aws_iam_policy_document" "enforce_tls_landing" {
  statement {
    sid     = "EnforceTLSRequestsOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.landing.arn,
      "${aws_s3_bucket.landing.arn}/*",
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# S3 bucket policy to enforce TLS for the archive bucket
data "aws_iam_policy_document" "enforce_tls_archive" {
  statement {
    sid     = "EnforceTLSRequestsOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.archive.arn,
      "${aws_s3_bucket.archive.arn}/*",
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
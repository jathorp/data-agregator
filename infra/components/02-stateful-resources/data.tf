# components/02-stateful-resources/data.tf – matches the simplified main.tf

# Who am I?
data "aws_caller_identity" "current" {}

# Pull the security component’s outputs (admin role ARN)
data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/00-security.tfstate"
    region = var.aws_region
  }
}

# S3 bucket policy to enforce TLS for the landing bucket
data "aws_iam_policy_document" "enforce_tls_landing" {
  statement {
    sid       = "EnforceTLSRequestsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
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
    sid       = "EnforceTLSRequestsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
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
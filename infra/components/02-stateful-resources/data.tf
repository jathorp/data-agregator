# components/02-stateful-resources/data.tf – matches the simplified main.tf

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

# S3 bucket policy to enforce TLS for the distribution bucket
data "aws_iam_policy_document" "enforce_tls_distribution" {
  statement {
    sid     = "EnforceTLSRequestsOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.distribution.arn,
      "${aws_s3_bucket.distribution.arn}/*",
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
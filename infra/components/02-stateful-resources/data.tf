# components/02-stateful-resources/data.tf

# Data source for the KMS policy.
data "aws_caller_identity" "current" {}

data "terraform_remote_state" "security" {
  backend = "s3"

  # The configuration is now dynamic and based on variables.
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/00-security.tfstate"
    region = var.aws_region
  }
}

data "aws_iam_policy_document" "kms_policy" {
  # Statement 1: Admin permissions
  statement {
    sid       = "EnableIAMUserPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type = "AWS"
      identifiers = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root",
        data.terraform_remote_state.security.outputs.kms_admin_role_arn
      ]
    }
  }

  # Statement 2: Lambda usage permissions
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
    resources = [aws_kms_key.app_key.arn]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.lambda_exec_role.arn]
    }
  }

  # Statement 3: SQS service permissions (THIS IS THE CRITICAL FIX)
  statement {
    sid    = "AllowSQSToUseKeyForEncryptedQueues"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["sqs.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey*"
    ]
    resources = [aws_kms_key.app_key.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        aws_sqs_queue.main.arn,
        aws_sqs_queue.dlq.arn
      ]
    }
  }
}
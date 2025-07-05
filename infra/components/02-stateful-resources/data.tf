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

# KMS‑key policy document – **no SQS stanza now**
data "aws_iam_policy_document" "kms_policy" {

  # ── Statement 1: give root and the security admin role full control
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

  # ── Statement 2: allow the Lambda execution role to use the key
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

  # (No SQS statement required, because the queues now use alias/aws/sqs)
}

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
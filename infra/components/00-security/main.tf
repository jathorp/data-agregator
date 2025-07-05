# infra/components/00-security/maim.tf

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "kms_admin" {
  name = var.kms_admin_role_name

  # This policy allows an IAM user/role in the same account to assume this role.
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = {
        AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      }
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "kms_admin_power_user" {
  role       = aws_iam_role.kms_admin.name
  policy_arn = "arn:aws:iam::aws:policy/AWSKeyManagementServicePowerUser"
}
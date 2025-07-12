# infra/components/00-security/maim.tf

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "kms_admin" {
  name = var.kms_admin_role_name

  description = "Administrative role for managing KMS keys for the ${var.project_name} project. Assumable by defined administrators."

  # Greatly restricted the trust policy ---
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = {
        AWS = var.kms_admin_principal_arns
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
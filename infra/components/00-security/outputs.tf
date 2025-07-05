# infra/components/00-security/outputs.tf

output "kms_admin_role_arn" {
  description = "The ARN of the newly created KMS administrative role."
  value       = aws_iam_role.kms_admin.arn
}
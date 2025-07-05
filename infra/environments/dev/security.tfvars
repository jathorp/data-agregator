# infra/environments/dev/security.tfvars

kms_admin_principal_arns = [
  "arn:aws:iam::123456789012:user/PrimaryDeveloper",
  "arn:aws:iam::123456789012:role/CICDPipelineRole"
  # Add the ARNs of the users or roles who should be allowed to use this role
]
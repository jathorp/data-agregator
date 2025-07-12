# infra/components/00-security/variables.tf

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment (e.g., 'dev', 'prod')."
  type        = string
}

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}

variable "kms_admin_role_name" {
  description = "The name for the KMS administrative role."
  type        = string
  default     = "DataAggregator-KMS-Admin"
}

variable "kms_admin_principal_arns" {
  description = "A list of IAM Principal ARNs (users, roles) that are allowed to assume the KMS Admin role."
  type        = list(string)
  # It's better to provide an empty list as a default and force the user
  # to explicitly define the principals in their .tfvars file.
  # This prevents accidentally deploying a role that nobody can assume.
}
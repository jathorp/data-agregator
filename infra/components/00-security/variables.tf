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
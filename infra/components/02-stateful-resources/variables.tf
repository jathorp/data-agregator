# components/02-stateful-resources/variables.tf

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
}

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}

variable "remote_state_bucket" {
  description = "The name of the S3 bucket where Terraform state is stored."
  type        = string
}

# --- S3 Variables ---
variable "landing_bucket_name" {
  description = "The base name for the S3 landing bucket."
  type        = string
}

variable "archive_bucket_name" {
  description = "The base name for the S3 archive bucket."
  type        = string
}

variable "distribution_bucket_name" {
  description = "The base name for the S3 distribution bucket (for the on-prem service to pull from)."
  type        = string
}

variable "s3_event_notification_prefix" {
  description = "The prefix for which S3 events should trigger the SQS notification. Allows for separating test data."
  type        = string
  default     = ""
}

# --- SQS Variables ---
variable "main_queue_name" {
  description = "The name of the main SQS processing queue."
  type        = string
}

variable "dlq_name" {
  description = "The name of the SQS Dead-Letter Queue."
  type        = string
}

# --- DynamoDB Variables ---
variable "idempotency_table_name" {
  description = "The name of the DynamoDB table for idempotency."
  type        = string
}

# The name for the Lambda's IAM role, which will be created here.
variable "lambda_role_name" {
  description = "The name for the Lambda function's IAM role."
  type        = string
}
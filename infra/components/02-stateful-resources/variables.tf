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
  description = "The base name for the S3 landing bucket. A random suffix will be added."
  type        = string
}

variable "archive_bucket_name" {
  description = "The base name for the S3 archive bucket. A random suffix will be added."
  type        = string
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

variable "circuit_breaker_table_name" {
  description = "The name of the DynamoDB table for the circuit breaker."
  type        = string
}

# Variable for the secret that will hold NiFi credentials.
variable "nifi_secret_name" {
  description = "The name of the secret in Secrets Manager to store NiFi credentials."
  type        = string
}

# The name for the Lambda's IAM role, which will be created here.
variable "lambda_role_name" {
  description = "The name for the Lambda function's IAM role."
  type        = string
}
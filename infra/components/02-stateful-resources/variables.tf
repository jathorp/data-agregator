# components/02-stateful-resources/variables.tf

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
}

variable "landing_bucket_name" {
  description = "The name of the S3 landing bucket."
  type        = string
}

variable "archive_bucket_name" {
  description = "The name of the S3 archive bucket."
  type        = string
}

variable "main_queue_name" {
  description = "The name of the main SQS processing queue."
  type        = string
}

variable "dlq_name" {
  description = "The name of the SQS Dead-Letter Queue."
  type        = string
}

variable "idempotency_table_name" {
  description = "The name of the DynamoDB table for idempotency."
  type        = string
}

variable "circuit_breaker_table_name" {
  description = "The name of the DynamoDB table for the circuit breaker."
  type        = string
}
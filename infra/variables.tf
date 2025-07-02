# File: variables.tf

variable "project_name" {
  description = "A short, unique name for the project (e.g., 'data-pipeline')."
  type        = string
  default     = "data-pipeline"
}

variable "environment" {
  description = "The deployment environment (e.g., 'dev', 'stg', 'prod')."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "The AWS region where resources will be deployed (e.g., 'eu-west-2')."
  type        = string
  default     = "eu-west-2"
}

variable "minio_secret_arn" {
  description = "The ARN of the AWS Secrets Manager secret for MinIO credentials."
  type        = string
  # No default, this must be provided.
}

variable "lambda_source_path" {
  description = "The absolute path to the directory containing the Python source code."
  type        = string
}

variable "minio_bucket" {
  description = "The destination bucket name in the MinIO instance."
  type        = string
}

variable "minio_sse_type" {
  description = "The server-side encryption type to use for MinIO uploads (e.g., 'AES256')."
  type        = string
  default     = "AES256"
}

variable "max_fetch_workers" {
  description = "The number of parallel threads used to download files from S3."
  type        = number
  default     = 8
}

variable "max_file_size_bytes" {
  description = "The maximum allowed size for any single file to be included in an archive."
  type        = number
  default     = 5242880 # 5 MB
}

variable "archive_timeout_seconds" {
  description = "The timeout for the archive writer thread to complete its work."
  type        = number
  default     = 300
}

variable "idempotency_ttl_hours" {
  description = "How long idempotency keys are kept in DynamoDB."
  type        = number
  default     = 192 # 8 days
}
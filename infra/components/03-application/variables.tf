variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
}

variable "remote_state_bucket" {
  description = "The name of the S3 bucket where Terraform state is stored."
  type        = string
}

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}

variable "lambda_artifacts_bucket_name" {
  description = "The name of the central S3 bucket for storing Lambda deployment packages."
  type        = string
}

variable "lambda_s3_key" {
  description = "The object key for the Lambda deployment package in the artifacts S3 bucket."
  type        = string
}

variable "lambda_function_name" {
  description = "The name of the Lambda function."
  type        = string
}

variable "lambda_handler" {
  description = "The handler for the Lambda function (e.g., 'app.handler')."
  type        = string
  default     = "app.handler"
}

variable "lambda_runtime" {
  description = "The runtime for the Lambda function."
  type        = string
  default     = "python3.12"
}

variable "lambda_timeout" {
  description = "The timeout in seconds for the Lambda function."
  type        = number
  default     = 60
}

variable "lambda_memory_size" {
  description = "The amount of memory in MB to allocate to the Lambda function."
  type        = number
  default     = 512
}

variable "lambda_ephemeral_storage_size" {
  description = "The size of the Lambda function's /tmp directory in MB. Min 512, Max 10240."
  type        = number
  default     = 2048
}

variable "idempotency_ttl_days" {
  description = "The number of days to retain the idempotency key in DynamoDB."
  type        = number
  default     = 7
}

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment (e.g., dev, staging, prod)."
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
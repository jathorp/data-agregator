# components/04-observability/variables.tf

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
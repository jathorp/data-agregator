# components/04-observability/variables.tf

variable "project_name" {
  type = string
}

variable "environment_name" {
  type = string
}

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}

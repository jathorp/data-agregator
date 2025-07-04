# modules/mock_nifi_endpoint/variables.tf

variable "project_name" {
  description = "Name of the project."
  type        = string
}

variable "environment_name" {
  description = "Name of the environment."
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC where the endpoint will be created."
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB."
  type        = list(string)
}
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

# UPDATED: Action 2 - The ALB is now placed in private subnets for better security.
variable "private_subnet_ids" {
  description = "List of private subnet IDs for the internal ALB."
  type        = list(string)
}
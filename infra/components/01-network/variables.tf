variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment (e.g., dev, staging, prod)."
  type        = string
}

variable "vpc_cidr_block" {
  description = "The CIDR block for the VPC."
  type        = string
}

variable "subnet_cidr_block" {
  description = "The CIDR block for the private subnet."
  type        = string
}
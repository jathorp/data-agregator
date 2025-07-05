# components/01-network/variables.tf

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

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}

# REFINED: Changed from list(string) to map(string) for explicit AZ-to-CIDR mapping.
variable "private_subnet_cidrs" {
  description = "A map of CIDR blocks for the private subnets, keyed by Availability Zone name."
  type        = map(string)
}

# REFINED: Changed from list(string) to map(string).
variable "public_subnet_cidrs" {
  description = "A map of CIDR blocks for the public subnets, keyed by Availability Zone name."
  type        = map(string)
}

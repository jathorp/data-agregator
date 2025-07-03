# We will create a very simple VPC and one private subnet for now.
# Note: We aren't creating modules yet, just defining resources directly.

locals {
  # Central place for tags to ensure consistency.
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = local.common_tags
}

resource "aws_subnet" "private" {
  vpc_id     = aws_vpc.main.id
  cidr_block = var.subnet_cidr_block
  tags       = merge(local.common_tags, { Name = "${var.project_name}-private-subnet" })
}
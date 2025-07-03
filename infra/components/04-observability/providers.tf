# File: providers.tf

terraform {
    required_version = "~> 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Configures the AWS provider with the target region and default tags.
provider "aws" {
  region = var.aws_region

  # Default tags are automatically applied to all taggable resources created
  # by this provider, ensuring consistent metadata for cost and security analysis.
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
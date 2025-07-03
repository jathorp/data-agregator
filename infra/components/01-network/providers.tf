# File: providers.tf

terraform {
  required_version = "~> 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }


  backend "s3" {
    # Add any configuration that is static and won't change.
    # This makes the block non-empty and silences the warning.
    region = "eu-west-2"
  }
}

provider "aws" {
  region = "eu-west-2"
}
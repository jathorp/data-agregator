# components/03-application/providers.tf

terraform {
  required_version = "~> 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    region = "eu-west-2"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}
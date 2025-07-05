# components/04-observability/providers.tf

terraform {
  required_version = "~> 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    region = "eu-west-2"
  }
}

provider "aws" {
  region = var.aws_region
}
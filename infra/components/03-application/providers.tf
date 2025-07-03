# components/03-application/providers.tf

terraform {
  required_version = "~> 1.5"

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
  region = "eu-west-2"
}
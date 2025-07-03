# This file is identical to the one in the network component.
# This consistency is key.

terraform {
    required_version = "~> 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = "eu-west-2"
}
# components/02-stateful-resources/providers.tf

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Pin to a specific major version to prevent breaking changes from auto-updates.
      # Allows any new 6.x version.
      version = "~> 6.0"
    }
  }

  # This block is intentionally sparse. It declares we are using an "s3" backend
  # and sets non-environment-specific options. All other configuration (bucket, key, region)
  # is passed dynamically by the `tf.sh` script during `terraform init`.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}

# This block configures the AWS provider itself.
# The region is passed in via a variable, allowing this component to be
# deployed to any region without code changes.
provider "aws" {
  region = var.aws_region
}
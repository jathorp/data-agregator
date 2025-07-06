# infra/components/03-application/data.tf

# Define the Terraform state bucket name in one central place for this component.
# This avoids hardcoding the same string in multiple data blocks below.
locals {
  remote_state_bucket = "data-aggregator-tfstate-dev"
}

# --- Data source to read outputs from the '01-network' component ---
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    # CORRECTED: Use the local variable instead of a non-existent var.*
    bucket = local.remote_state_bucket
    key    = "components/01-network/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}

# --- Data source to read outputs from the '02-stateful-resources' component ---
data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    # CORRECTED: Use the local variable here as well.
    bucket = local.remote_state_bucket
    key    = "components/02-stateful-resources/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}

# --- Data sources to get general AWS account information ---
data "aws_region" "current" {}

data "aws_caller_identity" "current" {}
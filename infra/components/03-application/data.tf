# infra/components/03-application/data.tf

# --- Data source to read outputs from the '01-network' component ---
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "components/01-network/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}

# --- Data source to read outputs from the '02-stateful-resources' component ---
data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "components/02-stateful-resources/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}

# --- Data sources to get general AWS account information ---
data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

# --- Data sources to get the prefix lists for S3 and DynamoDB ---

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${data.aws_region.current.id}.s3"
}

data "aws_prefix_list" "dynamodb" {
  name = "com.amazonaws.${data.aws_region.current.id}.dynamodb"
}
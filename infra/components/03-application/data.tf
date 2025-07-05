# infra/components/03-application/data.tf

data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/01-network.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/02-stateful-resources.tfstate"
    region = var.aws_region
  }
}

# --- AWS Service Data Sources ---

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
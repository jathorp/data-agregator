# components/04-observability/data.tf

data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    # Corrected key path
    key    = "components/02-stateful-resources/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "application" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    # Corrected key path
    key    = "components/03-application/${var.environment_name}.tfstate"
    region = var.aws_region
  }
}
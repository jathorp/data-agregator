# components/04-observability/data.tf

data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/02-stateful-resources.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "application" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/03-application.tfstate"
    region = var.aws_region
  }
}
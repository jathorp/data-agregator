# components/02-stateful-resources/data.tf – matches the simplified main.tf

# Who am I?
data "aws_caller_identity" "current" {}

# Pull the security component’s outputs (admin role ARN)
data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    bucket = var.remote_state_bucket
    key    = "${var.environment_name}/components/00-security.tfstate"
    region = var.aws_region
  }
}

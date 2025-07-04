# components/04-observability/data.tf

data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    # UPDATED: Action 1 - Corrected the key to match the stateful component's path.
    key    = "dev/components/02-stateful-resources.tfstate"
    region = "eu-west-2"
  }
}

data "terraform_remote_state" "application" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    key    = "dev/components/03-application.tfstate"
    region = "eu-west-2"
  }
}
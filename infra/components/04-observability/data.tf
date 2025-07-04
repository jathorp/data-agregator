# components/04-observability/data.tf

data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    key    = "dev/components/02-data-pipeline.tfstate"
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
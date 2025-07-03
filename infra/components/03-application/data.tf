# components/03-application/data.tf

# Read outputs from the 01-network component
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    key    = "dev/components/01-network.tfstate"
    region = "eu-west-2"
  }
}

# Read outputs from the 02-stateful-resources component
data "terraform_remote_state" "stateful" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev"
    key    = "dev/components/02-data-pipeline.tfstate"
    region = "eu-west-2"
  }
}
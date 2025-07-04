# components/02-stateful-resources/data.tf

data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "data-agregator-tfstate-2-dev" # This must match the backend config
    key    = "dev/components/01-network.tfstate" # The exact key for the network state
    region = "eu-west-2"
  }
}
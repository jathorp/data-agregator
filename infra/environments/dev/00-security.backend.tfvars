# infra/environments/dev/00-security.backend.tfvars

# Backend configuration for the security component in the dev environment
bucket = "data-aggregator-tfstate-dev" # Use your actual tfstate bucket name
key    = "dev/components/00-security.tfstate"
region = "eu-west-2" # Use your actual region
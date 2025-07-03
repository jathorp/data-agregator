# Configuration for the S3 backend where Terraform state is stored.
# This single bucket and table will hold the state for ALL components in the dev environment.

bucket         = "data-agregator-tfstate-dev"
dynamodb_table = "data-agregator-tfstate-dev-locks"
region         = "eu-west-2"
# Configuration for the S3 backend where Terraform state is stored.
# This single bucket and table will hold the state for ALL components in the dev environment.

bucket         = "data-agregator-tfstate-2-dev"
dynamodb_table = "data-agregator-tfstate-dev-2-locks"
region         = "eu-west-2"
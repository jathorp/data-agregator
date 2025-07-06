# environments/dev/03-application.backend.tfvars

# Backend configuration for the security component in the dev environment
bucket = "data-aggregator-tfstate-dev"

# The path to the state file within the S3 bucket.
key = "components/00-security/dev.tfstate"

# The AWS region where the S3 bucket resides.
region = "eu-west-2"
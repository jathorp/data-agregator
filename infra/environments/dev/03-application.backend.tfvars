# environments/dev/03-application.backend.tfvars

# Backend configuration for the security component in the dev environment
bucket = "data-aggregator-tfstate-dev"

# The path to the state file within the S3 bucket.
# The structure should be `components/<component-name>/<environment-name>.tfstate`.
# We will migrate to this path after the next full environment destroy/re-create.
# key = "components/00-security/dev.tfstate"
key = "dev/components/03-application.tfstate"

# The AWS region where the S3 bucket resides.
region = "eu-west-2"
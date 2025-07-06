# environments/dev/common.tfvars

project_name     = "data-aggregator"
environment_name = "dev"
aws_region       = "eu-west-2"

# The name of the central, shared S3 bucket for storing software artifacts.
# This bucket is managed externally by the 'create-artifact-bucket.sh' script.
lambda_artifacts_bucket_name = "verify-artifacts-111-eu-west-2"
# environments/dev/application.tfvars

# Variables specific to the '03-application' component.

lambda_s3_key                 = "artifacts/data-aggregator/dev/lambda.zip"
lambda_function_name          = "data-aggregator-processor-dev"
lambda_handler                = "app.handler"
lambda_runtime                = "python3.13"
lambda_memory_size            = 512
lambda_ephemeral_storage_size = 2048

# The name of the central, shared S3 bucket for storing software artifacts.
# This bucket is managed externally by the 'create-artifact-bucket.sh' script.
lambda_artifacts_bucket_name = "verify-artifacts-111-eu-west-2"
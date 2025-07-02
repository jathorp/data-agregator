# File: infra/terraform.tfvars

# --- Required Variables ---

minio_secret_arn   = "<YOUR_SECRET_ARN_HERE>"
lambda_source_path = "../src" # Assumes your 'src' folder is outside 'infra'
minio_bucket       = "data-archive"

# --- Optional Overrides (examples) ---
# You can override any variable with a default value here if needed.
#
# environment = "stg"
# aws_region  = "us-east-1"
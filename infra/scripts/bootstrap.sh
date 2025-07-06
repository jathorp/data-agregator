#!/bin/bash
# This script creates a Terraform state bucket if it doesn't exist and
# idempotently applies all required security settings.

set -e

# --- Configuration ---
# The name of the S3 bucket to create for storing Terraform state.
# This MUST match the bucket name in your *.backend.tfvars files.
BUCKET_NAME="data-aggregator-tfstate-dev"
REGION="eu-west-2"
# --- End Configuration ---

echo "🔹 Verifying setup for Terraform state bucket: '$BUCKET_NAME'..."

# --- 1. Create Bucket If It Doesn't Exist ---
# Use `head-bucket` to check for existence. If it fails, create the bucket.
if aws s3api head-bucket --bucket "$BUCKET_NAME" &> /dev/null; then
  echo "   ✅ Bucket '$BUCKET_NAME' already exists."
else
  echo "   ℹ️ Bucket '$BUCKET_NAME' not found. Creating it..."
  aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
  echo "   ✅ Bucket created."
fi

# --- 2. Idempotently Apply Security Settings ---
echo "🔹 Ensuring bucket security configuration is up to date..."

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled
echo "   ✅ Versioning is enabled."

# Enable default encryption
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration '{
      "Rules": [
        {
          "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" }
        }
      ]
    }'
echo "   ✅ Default encryption (AES256) is enabled."

# Block all public access
aws s3api put-public-access-block \
 --bucket "$BUCKET_NAME" \
 --public-access-block-configuration '{
     "BlockPublicAcls": true,
     "IgnorePublicAcls": true,
     "BlockPublicPolicy": true,
     "RestrictPublicBuckets": true
   }'
echo "   ✅ Public access is blocked."
echo
echo "✅🚀 Bootstrap complete. The state bucket is correctly configured."
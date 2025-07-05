#!/bin/bash

# --- Configuration ---
# The name of the S3 bucket to create for storing Terraform state.
# This MUST match the bucket name in your *.backend.tfvars files.
BUCKET_NAME="data-aggregator-tfstate-dev"
REGION="eu-west-2"
# --- End Configuration ---


set -e
echo "🔹 Creating S3 bucket '$BUCKET_NAME' for Terraform state..."

# 1. Create the S3 bucket.
# The LocationConstraint is required for regions other than us-east-1.
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"

echo "   ✅ Bucket created."

# 2. Enable versioning to protect against state file corruption or accidental deletion.
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled

echo "   ✅ Versioning enabled."

# 3. Enable default server-side encryption for all objects in the bucket.
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration '{
      "Rules": [
        {
          "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" }
        }
      ]
    }'

echo "   ✅ Default encryption (AES256) enabled."

# 4. Block all public access to the bucket.
aws s3api put-public-access-block \
 --bucket "$BUCKET_NAME" \
 --public-access-block-configuration '{
     "BlockPublicAcls": true,
     "IgnorePublicAcls": true,
     "BlockPublicPolicy": true,
     "RestrictPublicBuckets": true
   }'

echo "   ✅ Public access blocked."
echo "✅ Terraform state bucket setup is complete."
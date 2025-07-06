#!/bin/bash
# This script builds the Lambda package, uploads it to S3, and updates the function code.
# It provides a fast deployment path for application code, decoupled from infrastructure.

set -euo pipefail

# --- Configuration ---
ENVIRONMENT=$1
if [ -z "$ENVIRONMENT" ]; then
  echo "❌ Error: No environment specified."
  echo "Usage: ./scripts/deploy-lambda.sh <environment>"
  exit 1
fi

echo "🚀 Starting Lambda deployment for environment: $ENVIRONMENT"

# --- Read configuration from Terraform variables ---
# This ensures we use the exact same names as our infrastructure.
PROJECT_ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)
STATEFUL_VARS_PATH="$PROJECT_ROOT_DIR/environments/$ENVIRONMENT/stateful-resources.tfvars"
APP_VARS_PATH="$PROJECT_ROOT_DIR/environments/$ENVIRONMENT/application.tfvars"

# Use grep/awk to parse values from tfvars files. This is more robust than hardcoding.
LAMBDA_FUNCTION_NAME=$(grep 'lambda_function_name' "$APP_VARS_PATH" | awk -F'"' '{print $2}')
LAMBDA_S3_KEY=$(grep 'lambda_s3_key' "$APP_VARS_PATH" | awk -F'"' '{print $2}')
# For the bucket, we'll read the stateful var since that component "owns" the bucket.
# In a real-world scenario, you might have a dedicated artifacts bucket.
S3_BUCKET_NAME=$(grep 'archive_bucket_name' "$STATEFUL_VARS_PATH" | awk -F'"' '{print $2}')

echo "   - Function Name: $LAMBDA_FUNCTION_NAME"
echo "   - S3 Bucket:     s3://$S3_BUCKET_NAME"
echo "   - S3 Key:        $LAMBDA_S3_KEY"
echo "-----------------------------------------------------"

# --- 1. Build the Artifact ---
# Change to the root of the repo to run the existing build script
cd "$PROJECT_ROOT_DIR"
echo "🔹 Building Lambda artifact using build.sh..."
# Assuming your build script is in the root, named 'build.sh'
./build.sh # Or whatever the name of your build script is
echo "   ✅ Build complete."

# --- 2. Upload to S3 ---
echo "🔹 Uploading artifact to S3..."
aws s3 cp "dist/lambda.zip" "s3://${S3_BUCKET_NAME}/${LAMBDA_S3_KEY}"
echo "   ✅ Upload complete."

# --- 3. Update Lambda Function Code ---
echo "🔹 Updating Lambda function code..."
aws lambda update-function-code \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --s3-bucket "$S3_BUCKET_NAME" \
  --s3-key "$LAMBDA_S3_KEY"
echo "   ✅ Function code updated."
echo
echo "✅ Lambda deployment to '$ENVIRONMENT' completed successfully!"
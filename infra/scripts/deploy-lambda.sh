#!/usr/bin/env bash
#
# Robust Lambda Deployment Script (v3 - Corrected Paths)
#
# This script can be run from any directory within the project. It automatically
# locates the project root (by finding 'pyproject.toml') and uses the correct
# relative paths for the 'infra' subdirectory.
#
set -euo pipefail

# --- Color Codes for Output ---
C_BLUE='\033[0;34m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_NC='\033[0m' # No Color

# --- Find Project Root ---
# This function searches up the directory tree to find the project root,
# identified by the presence of a 'pyproject.toml' file.
find_project_root() {
  local dir
  dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" ]]; then
      echo "$dir"
      return
    fi
    dir=$(dirname "$dir")
  done
  echo "" # Return empty if not found
}

# --- Main Script Logic ---

# Check for environment argument (e.g., 'dev', 'prod')
if [ -z "${1-}" ]; then
  echo -e "${C_RED}❌ Error: Missing environment argument.${C_NC}"
  echo "   Usage: $0 <environment>"
  echo "   Example: $0 dev"
  exit 1
fi
ENVIRONMENT=$1

echo -e "${C_BLUE}=====================================================${C_NC}"
echo "🚀 Starting Robust Lambda Deployment for '${C_GREEN}$ENVIRONMENT${C_NC}'"
echo -e "${C_BLUE}=====================================================${C_NC}"

# Locate the project root. Exit if not found.
PROJECT_ROOT=$(find_project_root)
if [ -z "$PROJECT_ROOT" ]; then
  echo -e "${C_RED}❌ Error: Could not find project root (marker file 'pyproject.toml' not found).${C_NC}"
  exit 1
fi
echo "🔹 Project root found at: $PROJECT_ROOT"

# CRITICAL STEP: Change to the project root directory.
# This simplifies all subsequent path handling.
cd "$PROJECT_ROOT"

# --- Define Paths (Corrected to include the 'infra' directory) ---
ENV_DIR="infra/environments/$ENVIRONMENT"
COMMON_VARS_PATH="$ENV_DIR/common.tfvars"
APP_VARS_PATH="$ENV_DIR/application.tfvars"
ZIP_FILE_PATH="dist/lambda.zip" # The 'dist' folder is at the root, which is correct.

if [ ! -d "$ENV_DIR" ]; then
    echo -e "${C_RED}❌ Error: Environment directory not found at '$ENV_DIR'${C_NC}"
    echo "   (Checked from project root: $PROJECT_ROOT)"
    exit 1
fi

# Helper function to parse variables from .tfvars files
get_tf_var() {
  grep "^$1" "$2" | sed -e 's/.*= *//' -e 's/"//g'
}


# --- Step 1: Build the Lambda Artifact ---
echo
echo "🔹 Running build script..."
# Run the build script using its path relative to the project root.
# NOTE: Your build.sh is at the root level, so this is correct.
if [ -f "build.sh" ]; then
    ./build.sh
else
    echo -e "${C_RED}❌ Error: Build script not found at project root 'build.sh'${C_NC}"
    exit 1
fi


if [ ! -f "$ZIP_FILE_PATH" ]; then
    echo -e "${C_RED}❌ Error: Build failed. Zip file not found at '$ZIP_FILE_PATH'${C_NC}"
    exit 1
fi

# --- Step 2: Read Configuration from .tfvars ---
echo
echo "🔹 Reading configuration..."
ARTIFACT_BUCKET=$(get_tf_var "lambda_artifacts_bucket_name" "$COMMON_VARS_PATH")
LAMBDA_S3_KEY=$(get_tf_var "lambda_s3_key" "$APP_VARS_PATH")
FUNCTION_NAME=$(get_tf_var "lambda_function_name" "$APP_VARS_PATH")
AWS_REGION=$(get_tf_var "aws_region" "$COMMON_VARS_PATH")

if [ -z "$ARTIFACT_BUCKET" ] || [ -z "$LAMBDA_S3_KEY" ] || [ -z "$FUNCTION_NAME" ] || [ -z "$AWS_REGION" ]; then
    echo -e "${C_RED}❌ Error: Could not read required variables from .tfvars files.${C_NC}"
    echo "   - Check 'lambda_artifacts_bucket_name' and 'aws_region' in '$COMMON_VARS_PATH'"
    echo "   - Check 'lambda_s3_key' and 'lambda_function_name' in '$APP_VARS_PATH'"
    exit 1
fi

echo "   - Artifact Bucket: $ARTIFACT_BUCKET"
echo "   - S3 Key:          $LAMBDA_S3_KEY"
echo "   - Function Name:   $FUNCTION_NAME"
echo "   - AWS Region:      $AWS_REGION"

# --- Step 3: Upload to S3 ---
S3_URI="s3://${ARTIFACT_BUCKET}/${LAMBDA_S3_KEY}"
echo
echo "🔹 Uploading artifact to $S3_URI..."
aws s3 cp "$ZIP_FILE_PATH" "$S3_URI" --region "$AWS_REGION"

# --- Step 4: Update Lambda Function Code ---
echo
echo "🔹 Updating Lambda function code for '${C_GREEN}$FUNCTION_NAME${C_NC}'..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --s3-bucket "$ARTIFACT_BUCKET" \
    --s3-key "$LAMBDA_S3_KEY" \
    --region "$AWS_REGION" \
    --publish > /dev/null # Suppress verbose JSON output

echo
echo -e "${C_GREEN}✅ Deployment complete!${C_NC}"
echo -e "${C_BLUE}=====================================================${C_NC}"
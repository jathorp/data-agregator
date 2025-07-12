#!/usr/bin/env bash
#
# Robust Lambda Deployment Script (v4 - WITH DEBUGGING)
#
set -euo pipefail

# --- Color Codes for Output ---
C_BLUE='\033[0;34m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_NC='\033[0m' # No Color
C_YELLOW='\033[0;33m'

# --- Find Project Root ---
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
  echo ""
}

# --- Main Script Logic ---
if [ -z "${1-}" ]; then
  echo -e "${C_RED}❌ Error: Missing environment argument.${C_NC}"
  echo "   Usage: $0 <environment>"
  exit 1
fi
ENVIRONMENT=$1

echo -e "${C_BLUE}=====================================================${C_NC}"
echo "🚀 Starting Robust Lambda Deployment for '${C_GREEN}$ENVIRONMENT${C_NC}'"
echo -e "${C_BLUE}=====================================================${C_NC}"

PROJECT_ROOT=$(find_project_root)
if [ -z "$PROJECT_ROOT" ]; then
  echo -e "${C_RED}❌ Error: Could not find project root (marker file 'pyproject.toml' not found).${C_NC}"
  exit 1
fi
echo "🔹 Project root found at: $PROJECT_ROOT"

cd "$PROJECT_ROOT"

ENV_DIR="infra/environments/$ENVIRONMENT"
COMMON_VARS_PATH="$ENV_DIR/common.tfvars"
APP_VARS_PATH="$ENV_DIR/application.tfvars"
ZIP_FILE_PATH="dist/lambda.zip"

if [ ! -d "$ENV_DIR" ]; then
    echo -e "${C_RED}❌ Error: Environment directory not found at '$ENV_DIR'${C_NC}"
    exit 1
fi

get_tf_var() {
  grep "^$1" "$2" | sed -e 's/.*= *//' -e 's/"//g'
}

# --- Step 1: Build ---
echo
echo "🔹 Running build script..."
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

# --- Step 2: Read Configuration ---
echo
echo "🔹 Reading configuration..."
ARTIFACT_BUCKET=$(get_tf_var "lambda_artifacts_bucket_name" "$COMMON_VARS_PATH" || true)
LAMBDA_S3_KEY=$(get_tf_var "lambda_s3_key" "$APP_VARS_PATH" || true)
FUNCTION_NAME=$(get_tf_var "lambda_function_name" "$APP_VARS_PATH" || true)
AWS_REGION=$(get_tf_var "aws_region" "$COMMON_VARS_PATH" || true)

# --- DEBUG BLOCK ---
# This will show us exactly what values the script is working with.
echo -e "${C_YELLOW}------------------- DEBUG -------------------${C_NC}"
echo -e "   Checking values read from .tfvars files:"
echo -e "   - ARTIFACT_BUCKET: '$ARTIFACT_BUCKET'"
echo -e "   - LAMBDA_S3_KEY:   '$LAMBDA_S3_KEY'"
echo -e "   - FUNCTION_NAME:   '$FUNCTION_NAME'"
echo -e "   - AWS_REGION:      '$AWS_REGION'"
echo -e "${C_YELLOW}---------------------------------------------${C_NC}"
# --- END DEBUG BLOCK ---

# This is the validation check that is likely causing the early exit.
if [ -z "$ARTIFACT_BUCKET" ] || [ -z "$LAMBDA_S3_KEY" ] || [ -z "$FUNCTION_NAME" ] || [ -z "$AWS_REGION" ]; then
    echo
    echo -e "${C_RED}❌ Error: Could not read one or more required variables from .tfvars files.${C_NC}"
    echo "   Please check that the following variables are defined:"
    echo "   - 'lambda_artifacts_bucket_name' and 'aws_region' in '$COMMON_VARS_PATH'"
    echo "   - 'lambda_s3_key' and 'lambda_function_name' in '$APP_VARS_PATH'"
    exit 1
fi

echo "   ✅ Configuration read successfully."

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
    --publish > /dev/null

echo
echo -e "${C_GREEN}✅ Deployment complete!${C_NC}"
echo -e "${C_BLUE}=====================================================${C_NC}"
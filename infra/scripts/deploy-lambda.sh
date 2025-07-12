#!/usr/bin/env bash
#
# Robust Lambda Deployment Script (v6 - Corrected Variable Location)
#
# This version correctly looks for `lambda_artifacts_bucket_name` in the
# application.tfvars file, matching the project's logical structure.
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

# --- ROBUST get_tf_var Function ---
get_tf_var() {
  local var_name="$1"
  local file_path="$2"
  if grep -q "^${var_name}" "${file_path}"; then
    grep "^${var_name}" "${file_path}" | sed -e 's/.*= *//' -e 's/"//g'
  else
    echo ""
  fi
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
BUILD_SCRIPT_PATH="build.sh"

if [ ! -d "$ENV_DIR" ]; then
    echo -e "${C_RED}❌ Error: Environment directory not found at '$ENV_DIR'${C_NC}"
    exit 1
fi

# --- Step 1: Build ---
echo
echo "🔹 Running build script from '$BUILD_SCRIPT_PATH'..."
if [ -f "$BUILD_SCRIPT_PATH" ]; then
    ./"$BUILD_SCRIPT_PATH"
else
    echo -e "${C_RED}❌ Error: Build script not found at project root: '$BUILD_SCRIPT_PATH'${C_NC}"
    exit 1
fi

if [ ! -f "$ZIP_FILE_PATH" ]; then
    echo -e "${C_RED}❌ Error: Build failed. Zip file not found at '$ZIP_FILE_PATH'${C_NC}"
    exit 1
fi

# --- Step 2: Read Configuration ---
echo
echo "🔹 Reading configuration..."
# ----------------------------- THE ONLY CHANGE IS HERE -----------------------------
# We now correctly look for the artifact bucket name in the application-specific vars file.
ARTIFACT_BUCKET=$(get_tf_var "lambda_artifacts_bucket_name" "$APP_VARS_PATH")
# -----------------------------------------------------------------------------------
LAMBDA_S3_KEY=$(get_tf_var "lambda_s3_key" "$APP_VARS_PATH")
FUNCTION_NAME=$(get_tf_var "lambda_function_name" "$APP_VARS_PATH")
AWS_REGION=$(get_tf_var "aws_region" "$COMMON_VARS_PATH")


if [ -z "$ARTIFACT_BUCKET" ] || [ -z "$LAMBDA_S3_KEY" ] || [ -z "$FUNCTION_NAME" ] || [ -z "$AWS_REGION" ]; then
    echo
    echo -e "${C_RED}❌ Error: Could not read one or more required variables from .tfvars files.${C_NC}"
    echo "   Please check that the following variables are defined:"
    echo "   - 'aws_region' in '$COMMON_VARS_PATH'"
    echo "   - 'lambda_artifacts_bucket_name', 'lambda_s3_key', and 'lambda_function_name' in '$APP_VARS_PATH'"
    exit 1
fi

echo "   ✅ Configuration read successfully."
echo "      - Artifact Bucket: $ARTIFACT_BUCKET"
echo "      - S3 Key:          $LAMBDA_S3_KEY"
echo "      - Function Name:   $FUNCTION_NAME"
echo "      - AWS Region:      $AWS_REGION"


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
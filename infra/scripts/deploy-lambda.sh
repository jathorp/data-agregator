#!/usr/bin/env bash

set -euo pipefail

# --- Color Codes for Output ---
C_BLUE='\033[0;34m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_NC='\033[0m' # No Color
C_YELLOW='\033[0;33m'

# --- Default Settings ---
VERBOSE=false
AWS_PROFILE_ARRAY=() # Use an array for robust optional argument handling

# --- Argument Parsing ---
if [ -z "${1-}" ]; then
  echo -e "${C_RED}❌ Error: Missing required environment argument.${C_NC}"
  echo "    Usage: $0 <environment> [--verbose] [--profile <aws-profile-name>]"
  exit 1
fi
ENVIRONMENT=$1
shift # Consume the environment argument

while (( "$#" )); do
  case "$1" in
    --verbose)
      VERBOSE=true
      shift
      ;;
    --profile)
      if [ -n "$2" ] && [ "${2:0:1}" != "-" ]; then
        AWS_PROFILE_ARRAY=("--profile" "$2")
        shift 2
      else
        echo -e "${C_RED}Error: Argument for --profile is missing${C_NC}" >&2
        exit 1
      fi
      ;;
    *) # unsupported flags
      echo "Error: Unsupported flag $1" >&2
      exit 1
      ;;
  esac
done

# --- Helper Functions ---
find_project_root() {
  local dir="$PWD"; while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" ]]; then echo "$dir"; return; fi
    dir=$(dirname "$dir")
  done
}

get_tf_var() {
  local var_name="$1"; local file_path="$2"
  if grep -q "^${var_name}" "${file_path}"; then
    grep "^${var_name}" "${file_path}" | sed -e 's/.*= *//' -e 's/"//g'
  else echo ""; fi
}

# --- Main Script Logic ---
echo -e "${C_BLUE}=====================================================${C_NC}"
echo "🚀 Starting Lambda Deployment for '${C_GREEN}$ENVIRONMENT${C_NC}'"
echo -e "${C_BLUE}=====================================================${C_NC}"

if [ "$VERBOSE" = true ]; then echo "🔹 Verbose mode enabled."; fi

PROJECT_ROOT=$(find_project_root)
if [ -z "$PROJECT_ROOT" ]; then echo -e "${C_RED}❌ Error: Could not find project root.${C_NC}"; exit 1; fi
echo "🔹 Project root found at: $PROJECT_ROOT"; cd "$PROJECT_ROOT"

# --- Path and Variable Definitions ---
ENV_DIR="infra/environments/$ENVIRONMENT"; COMMON_VARS_PATH="$ENV_DIR/common.tfvars"; APP_VARS_PATH="$ENV_DIR/application.tfvars"
ZIP_FILE_PATH="dist/lambda.zip"; BUILD_SCRIPT_PATH="build.sh"

if [ ! -d "$ENV_DIR" ]; then echo -e "${C_RED}❌ Error: Env directory not found at '$ENV_DIR'${C_NC}"; exit 1; fi

# --- Step 1: Build ---
echo; echo "🔹 Running build script..."
if [ ! -f "$BUILD_SCRIPT_PATH" ]; then echo -e "${C_RED}❌ Error: Build script not found at '$BUILD_SCRIPT_PATH'${C_NC}"; exit 1; fi

if [ "$VERBOSE" = true ]; then
  ./"$BUILD_SCRIPT_PATH"
else
  # Suppress only stdout from the build script, allowing stderr to show build errors.
  ./"$BUILD_SCRIPT_PATH" > /dev/null
fi
if [ ! -f "$ZIP_FILE_PATH" ]; then echo -e "${C_RED}❌ Error: Build failed.${C_NC}"; exit 1; fi
echo "    ✅ Build complete."

# --- Step 2: Read & Confirm Configuration ---
echo; echo "🔹 Reading configuration..."
ARTIFACT_BUCKET=$(get_tf_var "lambda_artifacts_bucket_name" "$APP_VARS_PATH"); LAMBDA_S3_KEY=$(get_tf_var "lambda_s3_key" "$APP_VARS_PATH")
FUNCTION_NAME=$(get_tf_var "lambda_function_name" "$APP_VARS_PATH"); AWS_REGION=$(get_tf_var "aws_region" "$COMMON_VARS_PATH")
if [ -z "$ARTIFACT_BUCKET" ] || [ -z "$LAMBDA_S3_KEY" ] || [ -z "$FUNCTION_NAME" ] || [ -z "$AWS_REGION" ]; then
    echo -e "${C_RED}❌ Error: Could not read one or more required variables. Check .tfvars files.${C_NC}"; exit 1
fi

echo -e "${C_YELLOW}----------------- DEPLOYMENT TARGET -----------------${C_NC}"
echo -e "    Function Name:   ${C_GREEN}${FUNCTION_NAME}${C_NC}"; echo -e "    Artifact Bucket: ${C_YELLOW}${ARTIFACT_BUCKET}${C_NC}"
echo -e "    Artifact Key:    ${C_YELLOW}${LAMBDA_S3_KEY}${C_NC}"; echo -e "    AWS Region:      ${C_YELLOW}${AWS_REGION}${C_NC}"
if [ ${#AWS_PROFILE_ARRAY[@]} -gt 0 ]; then echo -e "    AWS Profile:     ${C_YELLOW}${AWS_PROFILE_ARRAY[1]}${C_NC}"; fi
echo -e "${C_YELLOW}---------------------------------------------------${C_NC}"
# CORRECTED: Added -r for robust "raw" reading, satisfying linters and best practices.
read -r -p "Press Enter to continue or Ctrl+C to abort..."

# --- Step 3: Upload to S3 ---
S3_URI="s3://${ARTIFACT_BUCKET}/${LAMBDA_S3_KEY}"; echo; echo "🔹 Uploading artifact to $S3_URI..."
if [ "$VERBOSE" = true ]; then
  aws "${AWS_PROFILE_ARRAY[@]}" s3 cp "$ZIP_FILE_PATH" "$S3_URI" --region "$AWS_REGION"
else
  aws "${AWS_PROFILE_ARRAY[@]}" s3 cp "$ZIP_FILE_PATH" "$S3_URI" --region "$AWS_REGION" > /dev/null
fi
echo "    ✅ Upload complete."

# --- Step 4: Check for Lambda and Update ---
echo; echo "🔹 Checking for existing Lambda function..."
# We suppress stdout to hide the successful JSON response, but allow stderr to show actual AWS errors (e.g., permissions).
if aws "${AWS_PROFILE_ARRAY[@]}" lambda get-function --function-name "$FUNCTION_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
  echo "    ✅ Function exists. Proceeding with code update."
  if [ "$VERBOSE" = true ]; then
    aws "${AWS_PROFILE_ARRAY[@]}" lambda update-function-code --function-name "$FUNCTION_NAME" --s3-bucket "$ARTIFACT_BUCKET" --s3-key "$LAMBDA_S3_KEY" --region "$AWS_REGION" --publish
  else
    aws "${AWS_PROFILE_ARRAY[@]}" lambda update-function-code --function-name "$FUNCTION_NAME" --s3-bucket "$ARTIFACT_BUCKET" --s3-key "$LAMBDA_S3_KEY" --region "$AWS_REGION" --publish > /dev/null
  fi
  echo; echo -e "${C_GREEN}✅ Deployment complete! The Lambda function has been updated.${C_NC}"
else
  echo -e "${C_YELLOW}    ⚠️ Function not found. This is normal for a first-time deployment.${C_NC}"
  echo; echo "    The build artifact has been uploaded. Next step is to create the infrastructure."
  echo; echo "    Next Action: Run ${C_GREEN}./tf.sh ${ENVIRONMENT} apply${C_NC} inside the ${C_BLUE}infra/components/03-application/${C_NC} directory."
  echo; echo -e "${C_GREEN}✅ Bootstrap upload complete!${C_NC}"
fi

echo -e "${C_BLUE}=====================================================${C_NC}"
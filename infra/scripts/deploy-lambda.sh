rsing & Path Configuration ---
ENVIRONMENT=$1
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_DIR="$PROJECT_ROOT_DIR/environments/$ENVIRONMENT"
COMMON_VARS_PATH="$ENV_DIR/common.tfvars"
APP_VARS_PATH="$ENV_DIR/application.tfvars"
ZIP_FILE_PATH="$PROJECT_ROOT_DIR/dist/lambda.zip"

if [ ! -d "$ENV_DIR" ]; then
    echo -e "${C_RED}❌ Error: Environment directory not found at $ENV_DIR${C_NC}"
    exit 1
fi

# --- Step 1: Build the Lambda Artifact ---
echo -e "${C_BLUE}=====================================================${C_NC}"
echo "🔹 Running build script..."
echo
"$PROJECT_ROOT_DIR/scripts/build.sh"
echo

if [ ! -f "$ZIP_FILE_PATH" ]; then
    echo -e "${C_RED}❌ Error: Build failed. Zip file not found at $ZIP_FILE_PATH${C_NC}"
    exit 1
fi

# --- Step 2: Read Configuration from .tfvars ---
echo "🔹 Reading configuration for environment: ${C_GREEN}$ENVIRONMENT${C_NC}"
ARTIFACT_BUCKET=$(get_tf_var "lambda_artifacts_bucket_name" "$COMMON_VARS_PATH")
LAMBDA_S3_KEY=$(get_tf_var "lambda_s3_key" "$APP_VARS_PATH")
FUNCTION_NAME=$(get_tf_var "lambda_function_name" "$APP_VARS_PATH")
AWS_REGION=$(get_tf_var "aws_region" "$COMMON_VARS_PATH")

if [ -z "$ARTIFACT_BUCKET" ] || [ -z "$LAMBDA_S3_KEY" ] || [ -z "$FUNCTION_NAME" ]; then
    echo -e "${C_RED}❌ Error: Could not read required variables from .tfvars files.${C_NC}"
    echo "   - Check lambda_artifacts_bucket_name in $COMMON_VARS_PATH"
    echo "   - Check lambda_s3_key and lambda_function_name in $APP_VARS_PATH"
    exit 1
fi

echo "   - Artifact Bucket: $ARTIFACT_BUCKET"
echo "   - S3 Key:          $LAMBDA_S3_KEY"
echo "   - Function Name:   $FUNCTION_NAME"
echo "   - AWS Region:      $AWS_REGION"
echo

# --- Step 3: Upload to S3 ---
S3_URI="s3://${ARTIFACT_BUCKET}/${LAMBDA_S3_KEY}"
echo "🔹 Uploading artifact to $S3_URI..."
aws s3 cp "$ZIP_FILE_PATH" "$S3_URI" --region "$AWS_REGION"
echo

# --- Step 4: Update Lambda Function Code ---
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


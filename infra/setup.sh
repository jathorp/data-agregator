#!/bin/bash
set -e

# --- Configuration ---
ENVIRONMENT=$1

if [ -z "$ENVIRONMENT" ]; then
  echo "❌ Error: No environment specified."
  echo "Usage: ./setup.sh <environment_name> (e.g., dev)"
  exit 1
fi

COMPONENTS=(
  "00-security"
  "01-network"
  "02-stateful-resources"
  "03-application"
  "04-observability"
)
# --- End Configuration ---

echo "🚀 Starting deployment for environment: $ENVIRONMENT"
echo "-----------------------------------------------------"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_DIR="$SCRIPT_DIR/environments/$ENVIRONMENT"

echo "🔹 Checking Terraform code formatting..."
terraform fmt -recursive -check
echo "   ✅ Code formatting is correct."

# Loop through each component in the defined order.
for component in "${COMPONENTS[@]}"; do
  echo "-----------------------------------------------------"
  echo "🔹 Deploying component: $component"
  echo "-----------------------------------------------------"

  COMPONENT_DIR="$SCRIPT_DIR/components/$component"
  cd "$COMPONENT_DIR"

  echo "   Running terraform init..."
  terraform init -input=false -reconfigure -backend-config="$ENV_DIR/$component.backend.tfvars"

  # --- CORRECTED: Use an array for optional arguments ---
  # This makes the script robust and passes variables only where needed.
  optional_args=()

  # Add common variables if the file exists.
  if [ -f "$ENV_DIR/common.tfvars" ]; then
    optional_args+=(-var-file "$ENV_DIR/common.tfvars")
  fi

  # Add component-specific variables if the file exists.
  COMPONENT_VARS_PATH="$ENV_DIR/${component#*-}.tfvars"
  if [ -f "$COMPONENT_VARS_PATH" ]; then
    optional_args+=(-var-file "$COMPONENT_VARS_PATH")
  fi

  echo "Using ${PROJECT_ROOT_DIR}/dist/lambda.zip"

  # Add the lambda artifact path ONLY for the application component.
  if [ "$component" == "03-application" ]; then
    optional_args+=(-var "lambda_artifact_path=${PROJECT_ROOT_DIR}/dist/lambda.zip")
  fi

  echo "   Running terraform apply..."
  terraform apply -input=false -auto-approve "${optional_args[@]}"

  cd "$SCRIPT_DIR"
done

echo "✅ Deployment for environment '$ENVIRONMENT' completed successfully!"
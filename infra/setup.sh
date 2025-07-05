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
  BACKEND_CONFIG="$ENV_DIR/$component.backend.tfvars"
  COMMON_VARS="$ENV_DIR/common.tfvars"
  COMPONENT_VARS="$ENV_DIR/${component#*-}.tfvars"

  cd "$COMPONENT_DIR"

  echo "   Running terraform init..."
  # Init is the only place we need the specific backend config file.
  terraform init -input=false -reconfigure -backend-config="$BACKEND_CONFIG"

  echo "   Running terraform apply..."
  # The apply command is simple again. All config is in .tfvars files.
  terraform apply -input=false -auto-approve \
    -var-file="$COMMON_VARS" \
    -var-file="$COMPONENT_VARS"

  cd "$SCRIPT_DIR"
done

echo "✅ Deployment for environment '$ENVIRONMENT' completed successfully!"
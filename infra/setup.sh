#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
# This ensures that if formatting fails or '01-network' fails, we don't proceed.
set -e

# --- Configuration ---
# The environment to deploy (e.g., "dev", "prod"). Passed as the first argument to the script.
ENVIRONMENT=$1

# An array defining the components in the correct deployment order.
COMPONENTS=(
  "01-network"
  "02-stateful-resources"
  "03-application"
  "04-observability"
)
# --- End Configuration ---


# --- Script Logic ---
# Check if an environment was provided.
if [ -z "$ENVIRONMENT" ]; then
  echo "❌ Error: No environment specified."
  echo "Usage: ./setup.sh <environment_name> (e.g., dev)"
  exit 1
fi

echo "🚀 Starting deployment for environment: $ENVIRONMENT"
echo "-----------------------------------------------------"

# Get the absolute path of the directory where the script is located.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
ENV_DIR="$SCRIPT_DIR/environments/$ENVIRONMENT"

# --- NEW: Run a format check on the entire project first ---
echo "🔹 Checking Terraform code formatting..."
# The '-recursive' flag checks all subdirectories.
# The '-check' flag makes the command fail if any files are not formatted.
terraform fmt -recursive -check
echo "   ✅ Code formatting is correct."
# --- End of New Step ---

# Loop through each component in the defined order.
for component in "${COMPONENTS[@]}"; do
  echo "-----------------------------------------------------"
  echo "🔹 Deploying component: $component"
  echo "-----------------------------------------------------"

  COMPONENT_DIR="$SCRIPT_DIR/components/$component"

  # Define paths for the backend and variable files.
  BACKEND_CONFIG="$ENV_DIR/$component.backend.tfvars"
  COMMON_VARS="$ENV_DIR/common.tfvars"
  COMPONENT_VARS="$ENV_DIR/${component#*-}.tfvars" # Removes the "01-", "02-" prefix

  # Change into the component's directory.
  cd "$COMPONENT_DIR"

  # Run Terraform commands.
  echo "   Running terraform init..."
  terraform init -input=false -backend-config="$BACKEND_CONFIG"

  echo "   Running terraform apply..."
  terraform apply -input=false -auto-approve \
    -var-file="$COMMON_VARS" \
    -var-file="$COMPONENT_VARS"

  # Go back to the root directory for the next loop iteration.
  cd "$SCRIPT_DIR"
done

echo "✅ Deployment for environment '$ENVIRONMENT' completed successfully!"
#!/bin/bash

# This script destroys all infrastructure for a given environment in the correct reverse order.
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# The environment to destroy (e.g., "dev"). Passed as the first argument to the script.
ENVIRONMENT=$1

# An array defining the components in the REVERSE order of creation for safe destruction.
COMPONENTS=(
  "04-observability"
  "03-application"
  "02-stateful-resources"
  "01-network"
)
# --- End Configuration ---


# --- Script Logic ---
# Check if an environment was provided.
if [ -z "$ENVIRONMENT" ]; then
  echo "❌ Error: No environment specified."
  echo "Usage: ./destroy.sh <environment_name> (e.g., dev)"
  exit 1
fi

echo "🔥 Starting destruction for environment: $ENVIRONMENT"
echo "   You have 5 seconds to cancel (Ctrl+C)..."
sleep 5

# Get the absolute path of the directory where the script is located.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
ENV_DIR="$SCRIPT_DIR/environments/$ENVIRONMENT"

# Loop through each component in the defined REVERSE order.
for component in "${COMPONENTS[@]}"; do
  echo "-----------------------------------------------------"
  echo "🔹 Destroying component: $component"
  echo "-----------------------------------------------------"

  COMPONENT_DIR="$SCRIPT_DIR/components/$component"

  # Define paths for the backend and variable files.
  BACKEND_CONFIG="$ENV_DIR/$component.backend.tfvars"
  COMMON_VARS="$ENV_DIR/common.tfvars"
  COMPONENT_VARS="$ENV_DIR/${component#*-}.tfvars"

  # Change into the component's directory.
  cd "$COMPONENT_DIR"

  # Initialize Terraform to read the state.
  echo "   Running terraform init..."
  terraform init -input=false -backend-config="$BACKEND_CONFIG"

  # Run terraform destroy.
  echo "   Running terraform destroy..."
  terraform destroy -input=false -auto-approve \
    -var-file="$COMMON_VARS" \
    -var-file="$COMPONENT_VARS"

  # Go back to the root directory for the next loop iteration.
  cd "$SCRIPT_DIR"
done

echo "✅ Destruction for environment '$ENVIRONMENT' completed successfully!"
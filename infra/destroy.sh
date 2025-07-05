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
  "00-security"
)
# --- End Configuration ---


# --- Script Logic ---
# Check if an environment was provided.
if [ -z "$ENVIRONMENT" ]; then
  echo "❌ Error: No environment specified."
  echo "Usage: ./destroy.sh <environment_name> (e.g., dev)"
  exit 1
fi

echo "🔥🔥🔥  D A N G E R  🔥🔥🔥"
echo "You are about to run a DESTRUCTIVE operation on the '$ENVIRONMENT' environment."
echo "This will permanently delete all managed infrastructure."
echo "You have 10 seconds to cancel (Ctrl+C)..."
sleep 10

# Get the absolute path of the directory where the script is located and the project root.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_DIR="$SCRIPT_DIR/environments/$ENVIRONMENT"

# Create a dummy lambda package if it doesn't exist to prevent errors.
LAMBDA_ZIP_PATH="${PROJECT_ROOT_DIR}/dist/lambda.zip"
if [ ! -f "$LAMBDA_ZIP_PATH" ]; then
  echo "🔹 Lambda package not found. Creating a dummy file to allow 'terraform destroy' to proceed..."
  mkdir -p "$(dirname "$LAMBDA_ZIP_PATH")"
  touch "${PROJECT_ROOT_DIR}/dist/dummy.txt"
  zip -j "$LAMBDA_ZIP_PATH" "${PROJECT_ROOT_DIR}/dist/dummy.txt" >/dev/null
  rm "${PROJECT_ROOT_DIR}/dist/dummy.txt"
fi

# Loop through each component in the defined REVERSE order.
for component in "${COMPONENTS[@]}"; do
  echo "-----------------------------------------------------"
  echo "🔹 Destroying component: $component"
  echo "-----------------------------------------------------"

  COMPONENT_DIR="$SCRIPT_DIR/components/$component"

  # Check if the component directory exists before proceeding.
  if [ ! -d "$COMPONENT_DIR" ]; then
    echo "   ⏩ Skipping component '$component' as its directory does not exist."
    continue
  fi

  # Change into the component's directory.
  cd "$COMPONENT_DIR"

  # Initialize Terraform.
  echo "   Running terraform init..."
  terraform init -input=false -reconfigure -backend-config="$ENV_DIR/$component.backend.tfvars"

  # Use an array to safely build all optional arguments for the destroy command.
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

  # Add lambda artifact path only for the application component.
  if [ "$component" == "03-application" ]; then
    optional_args+=(-var "lambda_artifact_path=${PROJECT_ROOT_DIR}/dist/lambda.zip")
  fi

  # Run terraform destroy with the dynamically built arguments.
  echo "   Running terraform destroy..."
  # FINAL CORRECTION: Removed '-auto-approve' for safety. Requires manual confirmation.
  terraform destroy "${optional_args[@]}"

  # Go back to the original script directory for the next loop iteration.
  cd "$SCRIPT_DIR"
done

echo "✅ Destruction for environment '$ENVIRONMENT' completed successfully!"
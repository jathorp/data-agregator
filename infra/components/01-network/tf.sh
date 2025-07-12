#!/bin/bash
# A robust wrapper for running Terraform in a component.
set -e

# --- Argument Parsing ---
if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: ./tf.sh <environment> <command> [args...]"
  echo "Example: ./tf.sh dev apply -auto-approve"
  echo "         ./tf.sh dev import aws_s3_bucket.my_bucket my-bucket-name"
  exit 1
fi
ENVIRONMENT=$1
COMMAND=$2
shift 2
TERRAFORM_ARGS=("$@")

# --- Backend Configuration ---
COMPONENT_NAME=$(basename "$PWD")
BACKEND_CONFIG_PATH="../../environments/$ENVIRONMENT/$COMPONENT_NAME.backend.tfvars"

if [ ! -f "$BACKEND_CONFIG_PATH" ]; then
    echo "❌ Error: Backend config not found at $BACKEND_CONFIG_PATH"
    exit 1
fi

# --- Initialize Terraform ---
echo "🔹 Initializing Terraform..."
terraform init -backend-config="$BACKEND_CONFIG_PATH"

# --- Run the main Terraform command ---
echo "🔹 Running terraform $COMMAND..."
if [[ "$COMMAND" == "import" ]]; then
    # Import does not use var-files
    terraform import "${TERRAFORM_ARGS[@]}"
else
    terraform "$COMMAND" "${TERRAFORM_ARGS[@]}"
fi

#!/bin/bash
# A robust wrapper for running Terraform in a component.
set -e

# --- Argument Parsing ---
if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: ./tf.sh <environment> <command> [var_file_args...]"
  exit 1
fi
ENVIRONMENT=$1
COMMAND=$2
shift 2
# All remaining arguments are passed directly to terraform
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
# The TERRAFORM_ARGS array will contain all the -var-file arguments from the orchestrator
# as well as any extra options like -auto-approve.
echo "🔹 Running terraform $COMMAND..."
terraform "$COMMAND" "${TERRAFORM_ARGS[@]}"
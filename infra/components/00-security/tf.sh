#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Standardized Terraform Wrapper ---
# This script provides a consistent interface for running Terraform commands
# for a specific component and environment. It is designed to be placed
# inside each component directory.

# --- Configuration & Functions ---

# Add some color to the output
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_NC='\033[0m' # No Color

# Function to display help message
show_help() {
  cat << EOF
A standardized Terraform wrapper script.

Usage: ./tf.sh <environment> <command> [terraform_options]

Arguments:
  <environment>       The target environment (e.g., "dev", "prod").
                      Corresponds to a directory in 'environments/'.
  <command>           The Terraform command to execute (e.g., "plan", "apply").
  [terraform_options] Optional flags or arguments to pass directly to Terraform.

Examples:
  ./tf.sh dev plan
  ./tf.sh prod apply
  ./tf.sh dev destroy
  ./tf.sh dev plan -out=dev.plan
  ./tf.sh dev state list
EOF
}

# --- Pre-flight Checks ---

# Check if Terraform is installed
if ! command -v terraform &> /dev/null; then
    echo -e "${C_RED}❌ Error: terraform could not be found. Please install it first.${C_NC}"
    exit 1
fi

# Check for 'help' command
if [[ "$1" == "help" || "$1" == "-h" || "$1" == "--help" ]]; then
  show_help
  exit 0
fi

# --- Argument Parsing & Validation ---

ENVIRONMENT=$1
COMMAND=$2

if [ -z "$ENVIRONMENT" ] || [ -z "$COMMAND" ]; then
  echo -e "${C_RED}❌ Error: Missing arguments.${C_NC}" >&2
  show_help
  exit 1
fi

# The rest of the arguments are stored in an array to be passed to Terraform.
# This correctly handles arguments with spaces.
shift 2
declare -a EXTRA_TF_ARGS=("$@")

# --- Path & Name Configuration ---
# Determines paths based on the script's location.
COMPONENT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd "$COMPONENT_DIR/../../" && pwd)
ENV_DIR="$PROJECT_ROOT_DIR/environments/$ENVIRONMENT"

# Dynamically get the component name (e.g., "security") from its directory name ("00-security").
COMPONENT_NAME=$(basename "$COMPONENT_DIR" | sed 's/^[0-9]*-//')
# Dynamically get the backend config filename (e.g., "00-security.backend.tfvars").
BACKEND_CONFIG_FILENAME=$(basename "$COMPONENT_DIR").backend.tfvars

# --- File Path Validation ---
BACKEND_VARS_PATH="$ENV_DIR/$BACKEND_CONFIG_FILENAME"
COMMON_VARS_PATH="$ENV_DIR/common.tfvars"
COMPONENT_VARS_PATH="$ENV_DIR/$COMPONENT_NAME.tfvars"

if [ ! -d "$ENV_DIR" ]; then
    echo -e "${C_RED}❌ Error: Environment directory not found at $ENV_DIR${C_NC}"
    exit 1
fi

if [ ! -f "$BACKEND_VARS_PATH" ]; then
    echo -e "${C_RED}❌ Error: Backend config not found at $BACKEND_VARS_PATH${C_NC}"
    exit 1
fi

echo -e "${C_BLUE}=====================================================${C_NC}"
echo -e "Component:      ${C_GREEN}$COMPONENT_NAME${C_NC}"
echo -e "Environment:    ${C_GREEN}$ENVIRONMENT${C_NC}"
echo -e "Command:        ${C_GREEN}terraform $COMMAND${C_NC}"
echo -e "Project Root:   $PROJECT_ROOT_DIR"
echo -e "${C_BLUE}=====================================================${C_NC}"
echo

# --- Terraform Execution ---

# Always run init first to ensure the backend and providers are correctly configured.
# -reconfigure is used to forcefully update the backend configuration.
echo "🔹 Initializing Terraform..."
terraform init -input=false -reconfigure -backend-config="$BACKEND_VARS_PATH"
echo

# Dynamically build the -var-file arguments.
declare -a VAR_FILES_ARGS
if [ -f "$COMMON_VARS_PATH" ]; then
  echo "🔹 Found common variables file: $COMMON_VARS_PATH"
  VAR_FILES_ARGS+=("-var-file=$COMMON_VARS_PATH")
fi
if [ -f "$COMPONENT_VARS_PATH" ]; then
  echo "🔹 Found component variables file: $COMPONENT_VARS_PATH"
  VAR_FILES_ARGS+=("-var-file=$COMPONENT_VARS_PATH")
fi
echo

# Execute the desired Terraform command, passing all variable files and extra arguments.
# Note: We are NOT using -auto-approve. This is a critical safety feature.
echo "🔹 Running 'terraform $COMMAND'..."
echo "-----------------------------------------------------"
terraform "$COMMAND" "${VAR_FILES_ARGS[@]}" "${EXTRA_TF_ARGS[@]}"
echo "-----------------------------------------------------"
echo -e "${C_GREEN}✅ Command completed successfully.${C_NC}"
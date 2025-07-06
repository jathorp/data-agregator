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

Usage: ./tf.sh <environment> <command_and_options>

Arguments:
  <environment>         The target environment (e.g., "dev", "prod").
                        Corresponds to a directory in 'environments/'.
  <command_and_options> The Terraform command to execute, including its subcommands
                        and any options (e.g., "plan", "apply", "state list").

Examples:
  ./tf.sh dev plan
  ./tf.sh prod apply
  ./tf.sh dev state list
  ./tf.sh dev plan -out=dev.plan
  ./tf.sh dev validate
EOF
}

# --- Pre-flight Checks ---

# Check if Terraform is installed
if ! command -v terraform &> /dev/null; then
    echo -e "${C_RED}❌ Error: terraform could not be found. Please install it first.${C_NC}"
    exit 1
fi

# Check for 'help' command or no arguments
if [[ "$1" == "help" || "$1" == "-h" || "$1" == "--help" || -z "$1" ]]; then
  show_help
  exit 0
fi

# --- Argument Parsing & Validation ---

ENVIRONMENT=$1
shift # Consume the environment argument

if [ "$#" -eq 0 ]; then
  echo -e "${C_RED}❌ Error: Missing terraform command.${C_NC}" >&2
  show_help
  exit 1
fi

# All remaining arguments comprise the command, subcommands, and options.
declare -a TF_COMMAND_AND_ARGS=("$@")
# For display and logic, we'll use the first element as the primary command.
MAIN_COMMAND="${TF_COMMAND_AND_ARGS[0]}"

# --- Path & Name Configuration ---
COMPONENT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd "$COMPONENT_DIR/../../" && pwd)
ENV_DIR="$PROJECT_ROOT_DIR/environments/$ENVIRONMENT"

COMPONENT_NAME=$(basename "$COMPONENT_DIR" | sed 's/^[0-9]*-//')
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
# Display the full command for clarity
echo -e "Command:        ${C_GREEN}terraform ${TF_COMMAND_AND_ARGS[*]}${C_NC}"
echo -e "Project Root:   $PROJECT_ROOT_DIR"
echo -e "${C_BLUE}=====================================================${C_NC}"
echo

# --- Terraform Execution ---

echo "🔹 Initializing Terraform..."
terraform init -input=false -reconfigure -backend-config="$BACKEND_VARS_PATH"
echo

# Dynamically build the -var-file arguments.
declare -a VAR_FILES_ARGS

# **IMPORTANT**: Only add -var-file for commands that support it.
# We use a whitelist for safety.
case "$MAIN_COMMAND" in
  plan|apply|destroy|console|import|refresh)
    if [ -f "$COMMON_VARS_PATH" ]; then
      echo "🔹 Found common variables file: $COMMON_VARS_PATH"
      VAR_FILES_ARGS+=("-var-file=$COMMON_VARS_PATH")
    fi
    if [ -f "$COMPONENT_VARS_PATH" ]; then
      echo "🔹 Found component variables file: $COMPONENT_VARS_PATH"
      VAR_FILES_ARGS+=("-var-file=$COMPONENT_VARS_PATH")
    fi
    ;;
  *)
    # For other commands like 'validate', 'fmt', 'state', etc., do not pass var files.
    echo "🔹 Skipping variable files for 'terraform $MAIN_COMMAND' command."
    ;;
esac
echo

# Execute the desired Terraform command.
echo "🔹 Running 'terraform ${TF_COMMAND_AND_ARGS[*]}'..."
echo "-----------------------------------------------------"
terraform "${TF_COMMAND_AND_ARGS[@]}" "${VAR_FILES_ARGS[@]}"
echo "-----------------------------------------------------"
echo -e "${C_GREEN}✅ Command completed successfully.${C_NC}"
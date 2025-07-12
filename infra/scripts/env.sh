#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Environment Orchestrator Script ---
# This script orchestrates Terraform commands across all components for an entire environment.
# It can run on all components in order or on a single, specified component.

# Add some color to the output
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_YELLOW='\033[0;33m'
C_NC='\033[0m' # No Color

# --- Configuration ---
COMPONENTS_TO_RUN=(
  "components/01-network"
  "components/02-stateful-resources"
  "components/03-application"
  "components/04-observability"
)

# --- Argument Parsing & Validation ---
show_help() {
  cat << EOF
Orchestrates Terraform commands across all components for an entire environment.

Usage: ./scripts/env.sh <environment> <command> [--component <name>] [terraform_options]

Arguments:
  <environment>   The target environment (e.g., "dev", "prod").
  <command>       The Terraform command to run (e.g., "plan", "apply", "destroy").

Options:
  --component <name>  Run the command only on a specific component (e.g., "01-network").

Examples:
  # Plan the entire 'dev' environment
  ./scripts/env.sh dev plan

  # Apply changes only to the stateful resources component
  ./scripts/env.sh dev apply --component 02-stateful-resources
EOF
}

if [[ "$1" == "help" || "$1" == "-h" || -z "$1" ]]; then
  show_help
  exit 0
fi

ENVIRONMENT=$1
COMMAND=$2
shift 2

# --- NEW: Parse optional --component flag and pass-through Terraform arguments ---
SPECIFIC_COMPONENT=""
TF_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --component)
      SPECIFIC_COMPONENT="$2"
      shift 2
      ;;
    *)
      TF_ARGS+=("$1") # Save other args to pass to terraform
      shift
      ;;
  esac
done

if [ -z "$ENVIRONMENT" ] || [ -z "$COMMAND" ]; then
  echo -e "${C_RED}❌ Error: Missing required arguments 'environment' and 'command'.${C_NC}" >&2
  show_help
  exit 1
fi

# --- NEW: Filter components if a specific one is requested ---
if [ -n "$SPECIFIC_COMPONENT" ]; then
  FOUND=0
  for path in "${COMPONENTS_TO_RUN[@]}"; do
    # Match if the path contains the component name (e.g., "01-network" in "components/01-network")
    if [[ "$path" == *"$SPECIFIC_COMPONENT"* ]]; then
      COMPONENTS_TO_RUN=("$path") # Replace the array with just the single component
      FOUND=1
      break
    fi
  done

  if [[ $FOUND -eq 0 ]]; then
    echo -e "${C_RED}❌ Error: Component '$SPECIFIC_COMPONENT' not found.${C_NC}" >&2
    exit 1
  fi
fi

# --- Main Logic ---
PROJECT_ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)
cd "$PROJECT_ROOT_DIR"

# --- Destroy Logic ---
if [ "$COMMAND" == "destroy" ]; then
  # This warning is especially important if running on the whole environment
  if [ -z "$SPECIFIC_COMPONENT" ]; then
    echo -e "${C_RED}🔥🔥🔥  D A N G E R  🔥🔥🔥${C_NC}"
    echo -e "${C_YELLOW}You are about to run a DESTRUCTIVE operation on the ENTIRE '$ENVIRONMENT' environment.${C_NC}"
    echo "You have 10 seconds to cancel (Ctrl+C)..."
    sleep 10
  fi

  REVERSED_COMPONENTS=()
  for i in $(seq $((${#COMPONENTS_TO_RUN[@]} - 1)) -1 0); do
    REVERSED_COMPONENTS+=("${COMPONENTS_TO_RUN[i]}")
  done
  COMPONENTS_TO_RUN=("${REVERSED_COMPONENTS[@]}")
fi

echo -e "${C_BLUE}=====================================================${C_NC}"
echo -e "Orchestrating Environment: ${C_GREEN}$ENVIRONMENT${C_NC}"
echo -e "Orchestrating Command:     ${C_GREEN}$COMMAND${C_NC}"
if [ -n "$SPECIFIC_COMPONENT" ]; then
  echo -e "Target Component:        ${C_GREEN}$SPECIFIC_COMPONENT${C_NC}"
fi
echo -e "${C_BLUE}=====================================================${C_NC}"

# Loop through each component in the (potentially filtered) list and execute the command.
for component_path in "${COMPONENTS_TO_RUN[@]}"; do
  component_name=$(basename "$component_path")
  echo
  echo -e "${C_YELLOW}--- Executing: $component_name ---${C_NC}"
  echo

  if [ -d "$component_path" ] && [ -f "$component_path/tf.sh" ]; then
    # Start with the common variables that all components need.
    TF_VAR_FILE_ARGS=("-var-file=../../environments/$ENVIRONMENT/common.tfvars")

    # Add component-specific var files using a case statement.
    case "$component_path" in
      "components/01-network")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/network.tfvars")
        ;;
      "components/02-stateful-resources")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/stateful-resources.tfvars")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars")
        ;;
      "components/03-application")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/application.tfvars")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars")
        ;;
      "components/04-observability")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars")
        ;;
    esac

    (
      cd "$component_path"
      ./tf.sh "$ENVIRONMENT" "$COMMAND" "${TF_VAR_FILE_ARGS[@]}" "${TF_ARGS[@]}"
    )
  else
    echo -e "${C_RED}⏩ Skipping. Could not find component or tf.sh script at '$component_path'${C_NC}"
  fi
done

echo
echo -e "${C_GREEN}✅ Orchestration for environment '$ENVIRONMENT' completed successfully!${C_NC}"
#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Environment Orchestrator Script ---
# This script orchestrates the deployment or destruction of an entire environment
# by calling the 'tf.sh' wrapper in each component directory in the correct order.

# Add some color to the output
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_YELLOW='\033[0;33m'
C_NC='\033[0m' # No Color

# --- Configuration ---
# Components in the correct order for CREATION.
# Destruction will automatically use the reverse of this order.
COMPONENTS=(
  "components/01-network"
  "components/02-stateful-resources"
  "components/03-application"
  "components/04-observability"
)

# --- Argument Parsing & Validation ---
show_help() {
  cat << EOF
Orchestrates Terraform commands across all components for an entire environment.

Usage: ./env.sh <environment> <command> [terraform_options]

Arguments:
  <environment>   The target environment (e.g., "dev", "prod").
  <command>       The Terraform command to run on all components (e.g., "plan", "apply", "destroy").

Examples:
  # Plan changes for the entire 'dev' environment
  ./env.sh dev plan

  # Apply changes to the 'prod' environment (will prompt for each component)
  ./env.sh prod apply

  # Pass options through to Terraform for CI/CD (use with extreme caution)
  ./env.sh dev apply -auto-approve

  # Destroy the 'dev' environment (will prompt for each component)
  ./env.sh dev destroy
EOF
}

if [[ "$1" == "help" || "$1" == "-h" || -z "$1" ]]; then
  show_help
  exit 0
fi

ENVIRONMENT=$1
COMMAND=$2
shift 2 # The rest of the arguments are passed through
TF_ARGS="$@"

if [ -z "$ENVIRONMENT" ] || [ -z "$COMMAND" ]; then
  echo -e "${C_RED}❌ Error: Missing arguments.${C_NC}" >&2
  show_help
  exit 1
fi

# --- Main Logic ---
# Get the script's directory to resolve component paths.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

# Reverse the array for 'destroy' command.
if [ "$COMMAND" == "destroy" ]; then
  echo -e "${C_RED}🔥🔥🔥  D A N G E R  🔥🔥🔥${C_NC}"
  echo -e "${C_YELLOW}You are about to run a DESTRUCTIVE operation on the entire '$ENVIRONMENT' environment.${C_NC}"
  echo "This will call 'terraform destroy' on each component in reverse order."
  echo "You have 10 seconds to cancel (Ctrl+C)..."
  sleep 10

  # Bash magic to reverse an array
  for i in $(seq $((${#COMPONENTS[@]} - 1)) -1 0); do
    REVERSED_COMPONENTS+=("${COMPONENTS[i]}")
  done
  COMPONENTS=("${REVERSED_COMPONENTS[@]}")
fi

echo -e "${C_BLUE}=====================================================${C_NC}"
echo -e "Orchestrating Environment: ${C_GREEN}$ENVIRONMENT${C_NC}"
echo -e "Orchestrating Command:     ${C_GREEN}$COMMAND${C_NC}"
echo -e "${C_BLUE}=====================================================${C_NC}"

# Loop through each component and execute the command.
for component_path in "${COMPONENTS[@]}"; do
  # Get just the directory name for logging.
  component_name=$(basename "$component_path")
  echo
  echo -e "${C_YELLOW}--- Executing: $component_name ---${C_NC}"
  echo

  if [ -d "$component_path" ] && [ -f "$component_path/tf.sh" ]; then
    (
      cd "$component_path"
      # Pass the environment, command, and any extra arguments to the component wrapper.
      ./tf.sh "$ENVIRONMENT" "$COMMAND" $TF_ARGS
    )
  else
    echo -e "${C_RED}⏩ Skipping. Could not find component or tf.sh script at '$component_path'${C_NC}"
  fi
done

echo
echo -e "${C_GREEN}✅ Orchestration for environment '$ENVIRONMENT' completed successfully!${C_NC}"
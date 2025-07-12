#!/bin/bash
# Exit immediately on error or unset variables
set -eu

# --- Environment Orchestrator Script ---
# Orchestrates Terraform commands across components.
# Supports running all, a single component, or listing components.

# --- Colors ---
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_YELLOW='\033[0;33m'
C_NC='\033[0m' # No Color

# --- Components ---
COMPONENTS_TO_RUN=(
  "components/01-network"
  "components/02-stateful-resources"
  "components/03-application"
  "components/04-observability"
)

FAILED_COMPONENTS=()

# --- Help ---
show_help() {
  cat << EOF
Usage: ./scripts/env.sh <environment> <command> [--component <name>] [--list-components] [terraform_options]

Arguments:
  <environment>           Environment to target (e.g., dev, prod)
  <command>                Terraform command (e.g., plan, apply, destroy)

Options:
  --component <name>       Run only the specified component (e.g., 01-network)
  --list-components        List available components and exit
  -h, help                 Show this help

Examples:
  ./scripts/env.sh dev plan
  ./scripts/env.sh dev apply --component 03-application
  ./scripts/env.sh dev destroy
EOF
}

# --- Argument Parsing ---
if [[ $# -eq 0 ]]; then
  show_help
  exit 0
fi

ENVIRONMENT=""
COMMAND=""
SPECIFIC_COMPONENT=""
TF_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|help)
      show_help; exit 0 ;;
    --list-components)
      echo "Available components:"
      for c in "${COMPONENTS_TO_RUN[@]}"; do
        echo "  - $(basename "$c")"
      done
      exit 0 ;;
    --component)
      SPECIFIC_COMPONENT="$2"
      shift 2 ;;
    *)
      if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT="$1"; shift
      elif [[ -z "$COMMAND" ]]; then
        COMMAND="$1"; shift
      else
        TF_ARGS+=("$1"); shift
      fi ;;
  esac
done

if [[ -z "$ENVIRONMENT" || -z "$COMMAND" ]]; then
  echo -e "${C_RED}❌ Error: Missing environment or command.${C_NC}"
  show_help
  exit 1
fi

# --- Filter Components if --component is set ---
if [[ -n "$SPECIFIC_COMPONENT" ]]; then
  FOUND=0
  for path in "${COMPONENTS_TO_RUN[@]}"; do
    if [[ "$path" == *"$SPECIFIC_COMPONENT"* ]]; then
      COMPONENTS_TO_RUN=("$path")
      FOUND=1
      break
    fi
  done

  if [[ $FOUND -eq 0 ]]; then
    echo -e "${C_RED}❌ Error: Component '$SPECIFIC_COMPONENT' not found.${C_NC}"
    exit 1
  fi
fi

# --- Destroy Confirmation ---
if [[ "$COMMAND" == "destroy" && -z "$SPECIFIC_COMPONENT" ]]; then
  echo -e "${C_RED}🔥🔥🔥  D A N G E R  🔥🔥🔥${C_NC}"
  echo -e "${C_YELLOW}You are about to destroy the entire '$ENVIRONMENT' environment.${C_NC}"
  echo "You have 10 seconds to cancel (Ctrl+C)..."
  sleep 10

  # reverse components
  REVERSED=()
  for (( i=${#COMPONENTS_TO_RUN[@]}-1; i>=0; i-- )); do
    REVERSED+=("${COMPONENTS_TO_RUN[$i]}")
  done
  COMPONENTS_TO_RUN=("${REVERSED[@]}")
fi

# --- Info ---
echo -e "${C_BLUE}=====================================================${C_NC}"
echo -e "Environment: ${C_GREEN}$ENVIRONMENT${C_NC}"
echo -e "Command:     ${C_GREEN}$COMMAND${C_NC}"
if [[ -n "$SPECIFIC_COMPONENT" ]]; then
  echo -e "Component:   ${C_GREEN}$SPECIFIC_COMPONENT${C_NC}"
fi
echo -e "${C_BLUE}=====================================================${C_NC}"

PROJECT_ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_ROOT_DIR"

# --- Main Loop ---
for component_path in "${COMPONENTS_TO_RUN[@]}"; do
  component_name=$(basename "$component_path")
  echo
  echo -e "${C_YELLOW}--- Executing: $component_name ---${C_NC}"
  echo

  if [[ -d "$component_path" && -f "$component_path/tf.sh" ]]; then
    TF_VAR_FILE_ARGS=("-var-file=../../environments/$ENVIRONMENT/common.tfvars")
    case "$component_path" in
      "components/01-network")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/network.tfvars") ;;
      "components/02-stateful-resources")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/stateful-resources.tfvars")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars") ;;
      "components/03-application")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/application.tfvars")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars") ;;
      "components/04-observability")
        TF_VAR_FILE_ARGS+=("-var-file=../../environments/$ENVIRONMENT/observability.tfvars") ;;
    esac

    if ! (
      cd "$component_path"
      ./tf.sh "$ENVIRONMENT" "$COMMAND" "${TF_VAR_FILE_ARGS[@]}" "${TF_ARGS[@]:-}"
    ); then
      echo -e "${C_RED}❌ $component_name failed.${C_NC}"
      FAILED_COMPONENTS+=("$component_name")
    fi

  else
    echo -e "${C_RED}⏩ Skipping: Missing component or tf.sh at '$component_path'${C_NC}"
    FAILED_COMPONENTS+=("$component_name")
  fi
done

# --- Summary ---
echo
if [[ ${#FAILED_COMPONENTS[@]} -eq 0 ]]; then
  echo -e "${C_GREEN}✅ All components completed successfully!${C_NC}"
else
  echo -e "${C_RED}❌ The following components failed:${C_NC}"
  for f in "${FAILED_COMPONENTS[@]}"; do
    echo -e "   - ${C_RED}$f${C_NC}"
  done
  exit 1
fi

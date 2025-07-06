#!/bin/bash
set -e

echo "🔹 Synchronizing Terraform wrapper scripts..."

PROJECT_ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)
TEMPLATE_FILE="$PROJECT_ROOT_DIR/scripts/tf.sh.template"
COMPONENTS_DIR="$PROJECT_ROOT_DIR/components"

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ Error: Template file not found at $TEMPLATE_FILE"
    exit 1
fi

for component in "$COMPONENTS_DIR"/*/; do
    if [ -d "$component" ]; then
        TARGET_FILE="${component}tf.sh"
        echo "   - Copying template to $TARGET_FILE"
        cp "$TEMPLATE_FILE" "$TARGET_FILE"
        chmod +x "$TARGET_FILE"
    fi
done

echo "✅ All wrapper scripts are now in sync."
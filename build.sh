#!/usr/bin/env bash
set -euo pipefail

# Get the project root directory
root_dir="$(dirname "$(dirname "$0")")"
cd "$root_dir"

# --- Configuration (matches your previous script) ---
runtime_py="3.13"
plat="aarch64-manylinux2014"

# --- 1. Clean up old artifacts and create a fresh staging area ---
echo "🔹 Cleaning up old artifacts..."
rm -rf build/ dist/ lambda.zip lambda_package.zip # Clean everything
mkdir -p build/python dist/

# --- 2. Install dependencies into the staging area ---
echo "🔹 Exporting dependencies from uv.lock..."
uv export --frozen --no-dev --no-editable -o build/requirements.txt

echo "🔹 Installing dependencies for Lambda environment..."
uv pip install \
  --no-installer-metadata \
  --no-compile-bytecode \
  --python-platform "$plat" \
  --python "$runtime_py" \
  --target build/python \
  -r build/requirements.txt

# --- 3. Copy ONLY the application code into the staging area ---
# This is the single, correct command to copy your app files to the root.
echo "🔹 Copying application source code..."
rsync -a --exclude='tests' --exclude='__pycache__' src/data_aggregator/ build/

# --- 4. Create the final, clean zip archive ---
echo "🔹 Creating zip archive..."
cd build
# Zip everything in the current directory, excluding cache files again as a safeguard
zip -qr ../dist/lambda.zip . -x "*__pycache__*"
cd .. # Go back to the project root

echo "✅ Lambda artifact created at $(pwd)/dist/lambda.zip"
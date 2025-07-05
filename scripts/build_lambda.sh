#!/usr/bin/env bash
set -euo pipefail
root_dir="$(dirname "$(dirname "$0")")"
cd "$root_dir"

runtime_py="3.13"                 # match aws runtime
# IMPORTANT: Change this if your Lambda is not ARM64/Graviton
plat="aarch64-manylinux2014"      # use aarch64-manylinux2014 for arm64

# --- Use build/ as a staging area ---
rm -rf build lambda_package.zip && mkdir -p build/python

# 1. freeze the exact pins from uv.lock -> requirements.txt
echo "🔹 Exporting dependencies from uv.lock..."
uv export --frozen --no-dev --no-editable -o build/requirements.txt

# 2. vendor third-party wheels into build/python
echo "🔹 Installing dependencies for Lambda environment..."
uv pip install \
  --no-installer-metadata \
  --no-compile-bytecode \
  --python-platform "$plat" \
  --python "$runtime_py" \
  --target build/python \
  -r build/requirements.txt

# 3. copy your application code
echo "🔹 Copying application source code..."
rsync -a --exclude='tests' src/ build/

# 4. zip the contents of the build directory
echo "🔹 Creating zip archive..."
mkdir -p dist # Ensure the dist directory exists
cd build
zip -qr ../dist/lambda.zip .
cd .. # Go back to the project root

echo "✅ Lambda artifact created at $(pwd)/dist/lambda.zip"
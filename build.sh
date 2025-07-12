#!/usr/bin/env bash
set -euo pipefail

root_dir="$(dirname "$0")"
cd "$root_dir"

runtime_py="3.13"
plat="aarch64-manylinux2014"

echo "🔹 Cleaning up old artifacts..."
rm -rf build/ dist/ lambda.zip
mkdir -p build/ dist/

echo "🔹 Installing dependencies..."
uv pip install \
  --no-installer-metadata \
  --no-compile-bytecode \
  --python-platform "$plat" \
  --python "$runtime_py" \
  --target build/ \
  --requirement uv.lock

echo "🔹 Adding application source code..."
rsync -av --exclude='__pycache__' src/ build/

echo "🔹 Creating zip archive..."
cd build
zip -qr ../dist/lambda.zip .
cd ..

echo "✅ Lambda artifact created at $(pwd)/dist/lambda.zip"

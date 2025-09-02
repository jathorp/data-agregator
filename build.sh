#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")"

rm -rf build dist
mkdir -p build dist

echo "🔹 Installing runtime dependencies with uv…"
uv pip install \
  --target build \
  --python "3.13" \
  --python-platform "aarch64-manylinux2014" \
  --no-compile-bytecode \
  --no-installer-metadata \
  .

echo "🔹 Copying application package…"
cp -R src/data_aggregator build/

# Strip __pycache__ to shrink size
find build -name '__pycache__' -type d -exec rm -rf {} +

echo "🔹 Creating ZIP…"
( cd build && zip -qr ../dist/lambda.zip . )

echo "✅ Lambda artefact ready: $(pwd)/dist/lambda.zip"

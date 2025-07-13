#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build dist
mkdir -p build dist

echo "🔹 Installing aws-lambda-powertools..."
uv pip install --upgrade --no-compile --target build aws-lambda-powertools[tracer]

echo "🔹 Copying package..."
cp -R src/data_aggregator build/

(cd build && zip -qr ../dist/lambda.zip .)
echo "✅ ZIP ready: $(pwd)/dist/lambda.zip"

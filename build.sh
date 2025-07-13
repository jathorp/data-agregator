#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")"

rm -rf build dist
mkdir -p build dist

echo "🔹 Copying package..."
cp -R src/data_aggregator build/

( cd build && zip -qr ../dist/lambda.zip . )
echo "✅ ZIP ready: $(pwd)/dist/lambda.zip"

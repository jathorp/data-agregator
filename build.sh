#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "🔹 Cleaning up..."
rm -rf build dist
mkdir -p build dist

echo "🔹 Copying app.py..."
cp src/app.py build/

echo "🔹 Creating ZIP..."
( cd build && zip -qr ../dist/lambda.zip . )

echo "✅ Lambda artifact: $(pwd)/dist/lambda.zip"

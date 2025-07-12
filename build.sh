#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build dist
mkdir -p build dist

# copy ONLY the package
cp -r src/data_aggregator build/

(cd build && zip -qr ../dist/lambda.zip .)
echo "ZIP ready: $(pwd)/dist/lambda.zip"

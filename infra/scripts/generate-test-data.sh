#!/bin/bash

# ==============================================================================
# generate-test-data.sh
#
# A utility script to generate and upload test files to an S3 bucket.
# Ideal for integration and load testing the data-aggregator pipeline.
#
# Dependencies:
#   - aws-cli (configured and authenticated)
#   - dd (standard on Linux/macOS)
#
# Examples
#
# ./scripts/generate-test-data.sh -b data-aggregator-landing-dev -s 5
# ./scripts/generate-test-data.sh -b data-aggregator-landing-dev -s 200
# ./scripts/generate-test-data.sh -b data-aggregator-landing-dev -s 1 -n 50 -p load-test/
# ==============================================================================

set -e # Exit immediately if a command exits with a non-zero status.

# --- Default values ---
NUM_FILES=1
S3_PREFIX=""

# --- Usage instructions ---
usage() {
  echo "Usage: $0 -b <bucket_name> -s <size_in_mb> [-n <num_files>] [-p <s3_prefix>]"
  echo "  -b <bucket_name>    (Required) The name of the S3 landing bucket."
  echo "  -s <size_in_mb>     (Required) The size of each test file to generate in Megabytes."
  echo "  -n <num_files>      (Optional) The number of files to generate. Default: 1."
  echo "  -p <s3_prefix>      (Optional) A prefix (folder) to use for the S3 object key."
  echo "  -h                  Display this help message."
  exit 1
}

# --- Parse command-line arguments ---
while getopts "b:s:n:p:h" opt; do
  case ${opt} in
    b ) S3_BUCKET=$OPTARG;;
    s ) FILE_SIZE_MB=$OPTARG;;
    n ) NUM_FILES=$OPTARG;;
    p ) S3_PREFIX=$OPTARG;;
    h ) usage;;
    \? ) usage;;
  esac
done

# --- Validate required arguments ---
if [ -z "${S3_BUCKET}" ] || [ -z "${FILE_SIZE_MB}" ]; then
  echo "Error: Missing required arguments."
  usage
fi

# --- Validate dependencies ---
if ! command -v aws >/dev/null 2>&1; then
    echo "Error: 'aws' command not found. Please install and configure the AWS CLI."
    exit 1
fi
if ! command -v dd >/dev/null 2>&1; then
    echo "Error: 'dd' command not found. This script requires a standard Unix-like environment."
    exit 1
fi

# --- Main loop ---
echo "Starting test data generation..."
for i in $(seq 1 "$NUM_FILES"); do
  local_filename="test-data-$(date +%s)-${i}.bin"

  echo "---"
  echo "-> Generating ${FILE_SIZE_MB}MB file: $local_filename..."
  # Use dd to create a file of the specified size with random binary data.
  # Suppress dd's own output for a cleaner log.
  dd if=/dev/urandom of="$local_filename" bs=1M count="$FILE_SIZE_MB" >/dev/null 2>&1

  echo "--> Uploading to s3://${S3_BUCKET}/${S3_PREFIX}${local_filename}..."
  # Use aws s3 cp, which will automatically handle multipart uploads for large files.
  aws s3 cp "$local_filename" "s3://${S3_BUCKET}/${S3_PREFIX}${local_filename}"

  echo "---> Cleaning up local file."
  rm "$local_filename"
done

echo -e "\n✅ All done. $NUM_FILES file(s) uploaded to s3://${S3_BUCKET}/${S3_PREFIX}"
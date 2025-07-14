#!/usr/bin/env bash
# ==============================================================================
# generate-test-data.sh ‒ v3.1
#
# Generates synthetic files and uploads them to an S3 bucket for pipeline
# testing.  Supports parallel uploads, random (incompressible) or zero-filled
# data, optional SSE, dry-run mode, and safe cleanup on Ctrl-C.
#
# Dependencies: aws-cli v2+, GNU coreutils (dd|fallocate), or macOS equivalents
# ------------------------------------------------------------------------------

set -euo pipefail

# ---------- Globals -----------------------------------------------------------
SCRIPT_NAME=$(basename "$0")
TMP_DIR=$(mktemp -d)
START_TIME=$(date +%s)

# Default parameters
NUM_FILES=1
FILE_SIZE_MB=""
S3_BUCKET=""
S3_PREFIX=""
CONCURRENCY=1
SSE=""
KEEP_LOCAL=false
DRY_RUN=false
USE_RANDOM_DATA=false

# Check for gdate on macOS for nanosecond support
DATE_CMD="date"
if [[ "$(uname)" == "Darwin" ]] && command -v gdate >/dev/null; then
  DATE_CMD="gdate"
fi

# ---------- Usage -------------------------------------------------------------
usage() {
  cat <<EOF
Usage: $SCRIPT_NAME -b <bucket> -s <sizeMB> [options]

Required:
  -b, --bucket        Target S3 bucket name
  -s, --size          Size of each file in MB

Optional:
  -n, --num           Number of files to generate      (default: 1)
  -p, --prefix        S3 object prefix (folder)        (default: "")
  -c, --concurrency   Parallel uploads                 (default: 1, >=1)
  --sse <alg>         Server-side encryption alg       (AES256 | aws:kms)
  --random            Use incompressible random data   (slower)
  --keep              Retain local files after upload
  --dry-run           Print actions without executing
  -h, --help          Show this help
EOF
  exit 1
}

# ---------- Argument parsing --------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--bucket)      S3_BUCKET=$2; shift 2;;
    -s|--size)        FILE_SIZE_MB=$2; shift 2;;
    -n|--num)         NUM_FILES=$2; shift 2;;
    -p|--prefix)      S3_PREFIX=$2; shift 2;;
    -c|--concurrency) CONCURRENCY=$2; shift 2;;
    --sse)            SSE=$2; shift 2;;
    --random)         USE_RANDOM_DATA=true; shift;;
    --keep)           KEEP_LOCAL=true; shift;;
    --dry-run)        DRY_RUN=true; shift;;
    -h|--help)        usage;;
    *) echo "Unknown option: $1" >&2; usage;;
  esac
done

# ---------- Validation --------------------------------------------------------
[[ -z $S3_BUCKET || -z $FILE_SIZE_MB ]] && {
  echo "Error: --bucket and --size are required." >&2; usage; }

[[ $NUM_FILES =~ ^[0-9]+$ && $FILE_SIZE_MB =~ ^[0-9]+$ && $CONCURRENCY =~ ^[0-9]+$ ]] || {
  echo "Error: numeric arguments required for -n, -s, -c." >&2; exit 1; }

(( CONCURRENCY > 0 && FILE_SIZE_MB > 0 )) || {
  echo "Error: --concurrency and --size must be > 0." >&2; exit 1; }

command -v aws >/dev/null 2>&1 || { echo "aws CLI not found." >&2; exit 1; }

# ---------- Cleanup traps -----------------------------------------------------
cleanup() {
  echo -e "\nCleaning up temp directory..."
  $KEEP_LOCAL || rm -rf "$TMP_DIR"
}
trap cleanup EXIT TERM
trap 'echo -e "\nCtrl-C detected. Cleaning up and exiting..."; cleanup; kill 0' INT

# ---------- Worker functions --------------------------------------------------
make_file() {
  local idx=$1
  local fname="${TMP_DIR}/test-$(${DATE_CMD} +%s%N)-${idx}.bin"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY] would create $fname"
    echo "$fname"
    return
  fi

  local data_source="zeros"
  if [[ "$USE_RANDOM_DATA" == "true" ]]; then
    data_source="random data"
  fi
  echo "[${idx}] Generating ${FILE_SIZE_MB}MB file with ${data_source}…"

  # --- ROBUST FILE CREATION BLOCK ---
  if [[ "$USE_RANDOM_DATA" == "true" ]]; then
    # For random data, dd is the only option
    dd if=/dev/urandom of="$fname" bs=1M count="$FILE_SIZE_MB" status=none
  else
    # For zero-filled data, try fast methods first and fall back to dd
    if command -v fallocate >/dev/null && fallocate -l "${FILE_SIZE_MB}M" "$fname" 2>/dev/null; then
      : # Success with fallocate (Linux)
    elif command -v mkfile >/dev/null && mkfile -n "${FILE_SIZE_MB}m" "$fname" 2>/dev/null; then
      : # Success with mkfile (macOS)
    else
      # Fallback to dd if fast methods are unavailable or fail
      echo "[${idx}] ... fast creation failed, using dd fallback."
      dd if=/dev/zero of="$fname" bs=1M count="$FILE_SIZE_MB" status=none
    fi
  fi
  # --- END ROBUST FILE CREATION BLOCK ---

  echo "$fname"
}

upload_file() {
  local file_path=$1
  local key="${S3_PREFIX}$(basename "$file_path")"
  local sse_args=()
  [[ -n $SSE ]] && sse_args+=(--sse "$SSE")

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY] would upload $file_path ➜ s3://$S3_BUCKET/$key"
    return
  fi

  aws s3 cp --no-progress "$file_path" "s3://$S3_BUCKET/$key" "${sse_args[@]}"
  echo "[✓] Uploaded $(basename "$file_path")"
  $KEEP_LOCAL || rm -f "$file_path"
}

process_item() {
  local idx=$1
  local path
  path=$(make_file "$idx")
  [[ -n $path ]] && upload_file "$path"
}

export -f make_file upload_file process_item
export FILE_SIZE_MB S3_BUCKET S3_PREFIX SSE DRY_RUN KEEP_LOCAL USE_RANDOM_DATA DATE_CMD

# ---------- Main --------------------------------------------------------------
data_kind=$([[ "$USE_RANDOM_DATA" == "true" ]] && echo "incompressible (random)" || echo "compressible (zeros)")
echo "### Test-data generator"
echo "Files     : $NUM_FILES × ${FILE_SIZE_MB} MB  ($data_kind)"
echo "Bucket    : s3://\"$S3_BUCKET\"/\"$S3_PREFIX\""
echo "Concurrency: \"$CONCURRENCY\" | SSE: \"${SSE:-none}\" | KEEP_LOCAL: \"$KEEP_LOCAL\" | DRY_RUN: \"$DRY_RUN\""
echo "Temp dir  : \"$TMP_DIR\""
echo "-----------------------------------------------------------------"

seq 1 "$NUM_FILES" | xargs -n 10 -P "$CONCURRENCY" bash -c '
  for i in "$@"; do
    process_item "$i"
  done
' _

END_TIME=$(date +%s)
TOTAL_MB=$(( NUM_FILES * FILE_SIZE_MB ))
summary="Completed"
[[ "$DRY_RUN" == "true" ]] && summary="(dry-run) completed"
printf "\n✅  %s: %d MB across %d object(s) in %ds.\n" \
       "$summary" "$TOTAL_MB" "$NUM_FILES" "$(( END_TIME - START_TIME ))"
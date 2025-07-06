#!/bin/bash
# This script provisions a central, secure S3 bucket for storing software artifacts
# like Lambda deployment packages. It is designed to be run once per account.
#
# It enforces a best-practice security posture, including:
#   - Encryption at rest (AES256)
#   - Blocked public access
#   - Versioning (for rollbacks)
#   - Object ownership controls
#   - Lifecycle policies (for cost management)

set -e

# --- Configuration ---
# The bucket name provided by your team.
# For maximum safety and uniqueness, enterprise buckets often include the AWS Account ID.
# However, we will use the name as specified.
BUCKET_NAME="verify-artifacts-111-eu-west-2"
REGION="eu-west-2"

# Tags to apply to the bucket for identification and cost allocation
OWNER_TAG="PlatformTeam" # Or your team's name
PROJECT_TAG="Shared-Artifacts"
# --- End Configuration ---

echo "This script will create or configure a foundational, shared artifact bucket."
echo "-------------------------------------------------------------------------"
echo "Bucket Name:      $BUCKET_NAME"
echo "Region:           $REGION"
echo "-------------------------------------------------------------------------"
read -p "Do you wish to continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# --- 1. Create Bucket If It Doesn't Exist ---
echo "🔹 Checking for bucket '$BUCKET_NAME'..."
if aws s3api head-bucket --bucket "$BUCKET_NAME" &> /dev/null; then
  echo "   ✅ Bucket already exists. Proceeding to apply configuration."
else
  echo "   ℹ️ Bucket not found. Creating it now..."
  aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
  echo "   ✅ Bucket created."
fi

# --- 2. Apply Security, Versioning, and Ownership Settings ---
echo "🔹 Applying security, versioning, and ownership settings..."

# Block all public access
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration '{ "BlockPublicAcls": true, "IgnorePublicAcls": true, "BlockPublicPolicy": true, "RestrictPublicBuckets": true }'
echo "   - Public access blocked."

# Enable server-side encryption by default
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration '{ "Rules": [{ "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" } }] }'
echo "   - Default encryption (AES256) enabled."

# Enable versioning to allow for rollbacks
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled
echo "   - Versioning enabled."

# Enforce that the bucket owner owns all uploaded objects. This simplifies permissions.
aws s3api put-bucket-ownership-controls \
  --bucket "$BUCKET_NAME" \
  --ownership-controls '{"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]}'
echo "   - Bucket owner enforced ownership enabled."

# --- 3. Apply Lifecycle Policy for Cost Management ---
echo "🔹 Applying lifecycle policy..."
# This policy does two things:
# 1. Deletes old, non-current object versions after 90 days (keeps recent rollback history).
# 2. Cleans up failed/incomplete multipart uploads after 7 days (good hygiene).
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET_NAME" \
  --lifecycle-configuration '{
      "Rules": [
        {
          "ID": "ExpireOldVersions",
          "Status": "Enabled",
          "Filter": { "Prefix": "" },
          "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
        },
        {
          "ID": "AbortIncompleteUploads",
          "Status": "Enabled",
          "Filter": { "Prefix": "" },
          "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 }
        }
      ]
    }'
echo "   - Expire old versions after 90 days."
echo "   - Abort incomplete uploads after 7 days."

# --- 4. Apply Tags ---
echo "🔹 Applying tags..."
aws s3api put-bucket-tagging \
  --bucket "$BUCKET_NAME" \
  --tagging "TagSet=[{Key=Owner,Value=${OWNER_TAG}}, {Key=Project,Value=${PROJECT_TAG}}]"
echo "   - Tags applied."
echo
echo "✅🚀 Foundational artifact bucket is now fully configured and ready for use."
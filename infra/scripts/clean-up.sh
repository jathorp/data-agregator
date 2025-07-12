#!/bin/bash
set -euo pipefail

echo "🔥 Resetting test environment…"

echo "🧹 Removing stale Terraform state…"
terraform state rm \
  aws_s3_bucket_lifecycle_configuration.access_logs || true
terraform state rm \
  aws_s3_bucket_lifecycle_configuration.landing || true
terraform state rm \
  aws_s3_bucket_lifecycle_configuration.archive || true
terraform state rm \
  aws_s3_bucket_lifecycle_configuration.distribution || true
terraform state rm \
  aws_s3_bucket.access_logs || true
terraform state rm \
  aws_s3_bucket.landing || true
terraform state rm \
  aws_s3_bucket.archive || true
terraform state rm \
  aws_s3_bucket.distribution || true
terraform state rm \
  aws_sqs_queue.main || true
terraform state rm \
  aws_sqs_queue.dlq || true
terraform state rm \
  aws_sqs_queue_policy.s3_to_sqs || true
terraform state rm \
  aws_s3_bucket_notification.landing_to_sqs || true

echo "✅ Terraform state cleaned."

echo "🪣 Cleaning up S3 buckets in AWS (if exist)…"
for bucket in $(aws s3 ls | awk '{print $3}'); do
  if [[ "$bucket" == data-aggregator-* ]]; then
    echo "  ⏳ Deleting bucket: $bucket"
    aws s3 rb "s3://$bucket" --force || true
  fi
done

echo "📬 Cleaning up SQS queues in AWS (if exist)…"
QUEUE_URLS=$(aws sqs list-queues --query 'QueueUrls' --output text || true)
for url in $QUEUE_URLS; do
  if [[ "$url" == *data-aggregator* ]]; then
    echo "  ⏳ Deleting queue: $url"
    aws sqs delete-queue --queue-url "$url" || true
  fi
done

echo "✅ AWS resources cleaned."

echo "📄 Reinitializing Terraform…"
terraform init

echo "🪄 Planning Terraform…"
terraform plan

echo "🚀 Applying Terraform…"
terraform apply -auto-approve

echo "🎉 Test environment reset & applied successfully!"

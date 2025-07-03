# components/02-stateful-resources/outputs.tf

# S3 Outputs
output "landing_bucket_id" {
  value = aws_s3_bucket.landing.id
}
output "archive_bucket_arn" {
  value = aws_s3_bucket.archive.arn
}

# SQS Outputs
output "main_queue_arn" {
  value = aws_sqs_queue.main.arn
}

# DynamoDB Outputs
output "idempotency_table_name" {
  value = aws_dynamodb_table.idempotency.name
}
output "circuit_breaker_table_name" {
  value = aws_dynamodb_table.circuit_breaker.name
}
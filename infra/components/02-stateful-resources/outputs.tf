# components/02-stateful-resources/outputs.tf

# S3 Outputs
output "landing_bucket_id" {
  description = "The ID of the S3 landing bucket."
  value       = aws_s3_bucket.landing.id
}
output "landing_bucket_arn" {
  description = "The ARN of the S3 landing bucket."
  value       = aws_s3_bucket.landing.arn
}
output "archive_bucket_id" {
  description = "The ID of the S3 archive bucket."
  value       = aws_s3_bucket.archive.id
}
output "archive_bucket_arn" {
  description = "The ARN of the S3 archive bucket."
  value       = aws_s3_bucket.archive.arn
}

output "distribution_bucket_id" {
  description = "The ID of the S3 distribution bucket."
  value       = aws_s3_bucket.distribution.id
}
output "distribution_bucket_arn" {
  description = "The ARN of the S3 distribution bucket."
  value       = aws_s3_bucket.distribution.arn
}

# SQS Outputs
output "main_queue_arn" {
  description = "The ARN of the main SQS queue."
  value       = aws_sqs_queue.main.arn
}
output "main_queue_name" {
  description = "The name of the main SQS queue."
  value       = aws_sqs_queue.main.name
}
output "dlq_arn" {
  description = "The ARN of the SQS Dead-Letter Queue."
  value       = aws_sqs_queue.dlq.arn
}
output "dlq_name" {
  description = "The name of the SQS Dead-Letter Queue."
  value       = aws_sqs_queue.dlq.name
}

# DynamoDB Outputs
output "idempotency_table_name" {
  description = "The name of the idempotency DynamoDB table."
  value       = aws_dynamodb_table.idempotency.name
}
output "idempotency_table_arn" {
  description = "The ARN of the idempotency DynamoDB table."
  value       = aws_dynamodb_table.idempotency.arn
}

# IAM Role Outputs
output "lambda_iam_role_arn" {
  description = "The ARN of the Lambda function's execution role."
  value       = aws_iam_role.lambda_exec_role.arn
}
output "lambda_iam_role_name" {
  description = "The name of the Lambda function's execution role."
  value       = aws_iam_role.lambda_exec_role.name
}
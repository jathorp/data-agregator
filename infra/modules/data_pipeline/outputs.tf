# File: infra/modules/data_pipeline/outputs.tf

output "s3_landing_bucket_id" {
  description = "The ID (name) of the S3 bucket for the landing zone."
  value       = aws_s3_bucket.landing_zone.id
}

output "lambda_function_name" {
  description = "The name of the data processing Lambda function."
  value       = aws_lambda_function.data_aggregator.function_name
}

output "sqs_queue_url" {
  description = "The URL of the main SQS queue."
  value       = aws_sqs_queue.main.url
}

output "dynamodb_table_name" {
  description = "The name of the DynamoDB table for idempotency."
  value       = aws_dynamodb_table.idempotency.name
}

output "lambda_log_group_name" {
  description = "The name of the CloudWatch Log Group for the Lambda."
  value       = "/aws/lambda/${aws_lambda_function.data_aggregator.function_name}"
}
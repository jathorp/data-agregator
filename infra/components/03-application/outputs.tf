# File: infra/outputs.tf

output "s3_landing_bucket" {
  description = "The name of the S3 bucket where files should be uploaded."
  value       = module.data_aggregator_pipeline.s3_landing_bucket_id
}

output "lambda_function" {
  description = "The name of the main data processing Lambda function."
  value       = module.data_aggregator_pipeline.lambda_function_name
}

output "sqs_queue" {
  description = "The URL of the main SQS queue."
  value       = module.data_aggregator_pipeline.sqs_queue_url
}

output "dynamodb_table" {
  description = "The name of the DynamoDB table used for idempotency."
  value       = module.data_aggregator_pipeline.dynamodb_table_name
}

output "lambda_log_group" {
  description = "The CloudWatch Log Group for the Lambda function. Use this to find logs."
  value       = module.data_aggregator_pipeline.lambda_log_group_name
}
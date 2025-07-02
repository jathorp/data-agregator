# File: infra/modules/data_pipeline/lambda.tf

# This data source automatically creates a ZIP archive from your Python source code.
data "archive_file" "lambda_package" {
  type        = "zip"
  source_dir  = var.lambda_source_path
  output_path = "${path.module}/lambda_package.zip"
}

# This defines the main Lambda function resource with all environment variables.
resource "aws_lambda_function" "data_aggregator" {
  function_name = "${local.resource_prefix}-lambda"
  role          = aws_iam_role.lambda_exec.arn

  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256

  handler       = "app.handler"
  runtime       = "python3.13"
  memory_size   = 1024
  timeout       = 45 # Seconds

  # Pass all necessary configuration to the Python code as environment variables.
  environment {
    variables = {
      # --- From Terraform resources ---
      LANDING_BUCKET    = aws_s3_bucket.landing_zone.id
      QUEUE_URL         = aws_sqs_queue.main.id
      IDEMPOTENCY_TABLE = aws_dynamodb_table.idempotency.id
      MINIO_SECRET_ID   = var.minio_secret_arn

      # --- From Terraform variables ---
      POWERTOOLS_SERVICE_NAME = var.project_name
      ENVIRONMENT             = var.environment
      MINIO_BUCKET            = var.minio_bucket
      MINIO_SSE_TYPE          = var.minio_sse_type
      IDEMPOTENCY_TTL_HOURS   = var.idempotency_ttl_hours
      MAX_FETCH_WORKERS       = var.max_fetch_workers
      MAX_FILE_SIZE_BYTES     = var.max_file_size_bytes
      ARCHIVE_TIMEOUT_SECONDS = var.archive_timeout_seconds

      # --- Hardcoded or less frequently changed values ---
      POWERTOOLS_METRICS_NAMESPACE = "DataMovePipeline"
      SECRET_CACHE_TTL_SECONDS     = "300"
      SPOOL_MAX_MEMORY_BYTES       = "268435456"
      QUEUE_PUT_TIMEOUT_SECONDS    = "5"
      MIN_REMAINING_TIME_MS        = "60000"
    }
  }
}

# This resource creates the trigger that connects the SQS queue to the Lambda function.
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.main.arn
  function_name    = aws_lambda_function.data_aggregator.arn
  batch_size       = 10
}
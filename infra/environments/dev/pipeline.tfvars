# Variables for stateful, application, and observability components in dev.

project_name        = "data-agregator"
environment_name    = "dev"
landing_bucket_name = "data-agregator-landing-dev"
archive_bucket_name = "data-agregator-bundles-archive-dev"

main_queue_name             = "data-agregator-main-queue-dev"
dlq_name                    = "data-agregator-dlq-dev"
idempotency_table_name      = "data-agregator-idempotency-dev"
circuit_breaker_table_name  = "data-agregator-circuit-breaker-dev"

lambda_function_name = "data-agregator-processor-dev"
lambda_handler       = "main.handler" # Assumes python file is main.py and function is handler
lambda_runtime       = "python3.11"
lambda_timeout       = 30 # seconds
lambda_memory_size   = 512 # MB
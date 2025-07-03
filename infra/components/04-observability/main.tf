# File: infra/main.tf

# This calls our single application module and passes all required variables.
module "data_aggregator_pipeline" {
  source = "./modules/data_pipeline"

  # Pass values from your root variables.tf into the module's variables
  project_name       = var.project_name
  environment        = var.environment
  minio_secret_arn   = var.minio_secret_arn
  lambda_source_path = var.lambda_source_path
  minio_bucket       = var.minio_bucket
}
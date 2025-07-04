# environments/dev/stateful.tfvars

# Variables specific to the '02-stateful-resources' component.

landing_bucket_name        = "data-aggregator-landing-dev"
archive_bucket_name        = "data-aggregator-archive-dev"
main_queue_name            = "data-aggregator-main-queue-dev"
dlq_name                   = "data-aggregator-dlq-dev"
idempotency_table_name     = "data-aggregator-idempotency-dev"
circuit_breaker_table_name = "data-agregator-circuit-breaker-dev"
nifi_secret_name           = "data-aggregator/nifi-credentials-dev"
# Note: Provide the actual ARN of a real administrative role here.
kms_admin_role_arn         = "arn:aws:iam::123456789012:role/TerraformAdmin"
lambda_role_name           = "data-aggregator-processor-role-dev"
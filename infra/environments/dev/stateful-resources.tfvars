# environments/dev/stateful-resources.tfvars

# Variables specific to the '02-stateful-resources' component.

landing_bucket_name        = "data-aggregator-landing-dev"
archive_bucket_name        = "data-aggregator-archive-dev"
main_queue_name            = "data-aggregator-main-queue-dev"
dlq_name                   = "data-aggregator-dlq-dev"
idempotency_table_name     = "data-aggregator-idempotency-dev"
circuit_breaker_table_name = "data-aggregator-circuit-breaker-dev"
nifi_secret_name           = "data-aggregator/nifi-credentials-dev"
lambda_role_name           = "data-aggregator-processor-role-dev"
remote_state_bucket        = "data-aggregator-tfstate-dev"
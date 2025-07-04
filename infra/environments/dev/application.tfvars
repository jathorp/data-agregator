# environments/dev/application.tfvars

# Variables specific to the '03-application' component.

lambda_function_name = "data-aggregator-processor-dev"
lambda_handler       = "handler.lambda_handler"
lambda_runtime       = "python3.13"
lambda_memory_size   = 512
lambda_ephemeral_storage_size = 2048

# These are not used for the 'dev' environment because it uses the mock endpoint,
# but they are required variables for the component. We can provide dummy values.
nifi_endpoint_url  = "https://placeholder.example.com"
nifi_endpoint_cidr = "0.0.0.0/32"
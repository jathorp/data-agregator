# environments/dev/application.tfvars

# Values for the '03-application' component

lambda_function_name = "data-aggregator-dev"

# Configuration for the NiFi endpoint this 'dev' environment should talk to.
nifi_endpoint_url  = "https://nifi-dev.onprem.example.com/contentListener"
nifi_endpoint_cidr = "10.100.10.5/32"
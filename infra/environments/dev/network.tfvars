# environments/dev/network.tfvars

project_name     = "data-aggregator"
environment_name = "dev"
vpc_cidr_block   = "10.0.0.0/16"

# Define the AZs we will use in eu-west-2
availability_zones = ["eu-west-2a", "eu-west-2b"]

# Provide a CIDR for each AZ defined above
public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
private_subnet_cidrs = ["10.0.101.0/24", "10.0.102.0/24"]
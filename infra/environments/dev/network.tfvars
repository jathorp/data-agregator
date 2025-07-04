# environments/dev/network.tfvars

# Variables specific to the '01-network' component.

vpc_cidr_block = "10.0.0.0/16"

public_subnet_cidrs = {
  "eu-west-2a" = "10.0.1.0/24",
  "eu-west-2b" = "10.0.2.0/24"
}

private_subnet_cidrs = {
  "eu-west-2a" = "10.0.101.0/24",
  "eu-west-2b" = "10.0.102.0/24"
}
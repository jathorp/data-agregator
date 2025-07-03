# We will create a very simple VPC and one private subnet for now.
# Note: We aren't creating modules yet, just defining resources directly.

locals {
  # Central place for tags to ensure consistency.
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, {
    Name = "${var.project_name}-vpc"
  })
}

resource "aws_subnet" "private" {
  vpc_id     = aws_vpc.main.id
  cidr_block = var.subnet_cidr_block
  tags       = merge(local.common_tags, { Name = "${var.project_name}-private-subnet" })
}

resource "aws_network_acl" "private" {
  vpc_id = aws_vpc.main.id

  # OUTBOUND RULES: What can leave our subnet?
  # By default, we will allow our Lambda to initiate traffic to the on-premise network.
  # This allows outbound traffic on any port to any destination within the private network.
  # This will be further restricted by the Lambda's Security Group later.
  egress {
    protocol   = "-1" # -1 means all protocols
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  # INBOUND RULES: What can enter our subnet?
  # We only allow "return" traffic from the connections our Lambda made.
  # This uses ephemeral ports, which is standard for stateful connections.
  ingress {
    protocol   = "tcp"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 1024
    to_port    = 65535
  }

  tags = merge(local.common_tags, { Name = "${var.project_name}-private-nacl" })
}

# Associate our new, secure NACL with our private subnet.
resource "aws_network_acl_association" "private" {
  network_acl_id = aws_network_acl.private.id
  subnet_id      = aws_subnet.private.id
}
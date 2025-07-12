# components/01-network/main.tf

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# --- Core VPC ---
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${var.project_name}-vpc" })
}

# --- Private Subnets (Multi-AZ) ---
# The Lambda functions will reside here, with no direct internet access.
resource "aws_subnet" "private" {
  for_each = var.private_subnet_cidrs

  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = merge(local.common_tags, { Name = "${var.project_name}-private-subnet-${each.key}" })
}

# --- Private Route Tables ---
# Note: There is no default route to an IGW or NAT Gateway.
# Outbound traffic is only possible to AWS services via VPC Endpoints.
resource "aws_route_table" "private" {
  for_each = aws_subnet.private
  vpc_id   = aws_vpc.main.id
  tags     = merge(local.common_tags, { Name = "${var.project_name}-private-rt-${each.key}" })
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}


# --- VPC Gateway Endpoints for S3 & DynamoDB ---
# These endpoints provide private, secure, and cost-effective access.
data "aws_region" "current" {}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.id}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.private : rt.id] # Associates with all private route tables
  tags              = local.common_tags
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.id}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.private : rt.id]
  tags              = local.common_tags
}

# --- VPC Interface Endpoints Security Group ---
# A dedicated security group for all interface endpoints.
resource "aws_security_group" "vpc_endpoints_sg" {
  name        = "${var.project_name}-vpc-endpoints-sg"
  description = "Allow inbound HTTPS traffic to VPC interface endpoints from within the VPC"
  vpc_id      = aws_vpc.main.id
  tags        = local.common_tags
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block] # Only allow traffic from within the VPC
  }
}

# --- VPC Interface Endpoints for SQS & KMS ---
resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.sqs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpc_endpoints_sg.id]
  tags                = local.common_tags
}

resource "aws_vpc_endpoint" "kms" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.kms"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpc_endpoints_sg.id]
  tags                = local.common_tags
}
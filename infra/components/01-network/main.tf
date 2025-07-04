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

# --- Subnets (Now Multi-AZ) ---
# Use for_each to create one of each subnet type in each specified Availability Zone.
resource "aws_subnet" "public" {
  for_each = toset(var.availability_zones)

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = var.public_subnet_cidrs[index(var.availability_zones, each.key)]
  map_public_ip_on_launch = true # Instances in public subnets get public IPs

  tags = merge(local.common_tags, { Name = "${var.project_name}-public-subnet-${each.key}" })
}

resource "aws_subnet" "private" {
  for_each = toset(var.availability_zones)

  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = var.private_subnet_cidrs[index(var.availability_zones, each.key)]

  tags = merge(local.common_tags, { Name = "${var.project_name}-private-subnet-${each.key}" })
}

# --- Internet Connectivity for Public Subnets ---
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${var.project_name}-igw" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(local.common_tags, { Name = "${var.project_name}-public-rt" })
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# --- Egress Connectivity for Private Subnets (via NAT Gateway) ---
# The NAT Gateway needs an Elastic IP and lives in a public subnet.
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${var.project_name}-nat-eip" })
}

resource "aws_nat_gateway" "main" {
  # For high availability, you could create a NAT Gateway in each AZ.
  # For simplicity and cost, we will start with one.
  allocation_id = aws_eip.nat.id
  subnet_id     = values(aws_subnet.public)[0].id # Place NAT in the first public subnet

  tags = merge(local.common_tags, { Name = "${var.project_name}-nat-gw" })

  # Explicitly depend on the IGW being created first.
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = merge(local.common_tags, { Name = "${var.project_name}-private-rt" })
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

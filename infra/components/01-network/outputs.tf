# components/01-network/outputs.tf

output "vpc_id" {
  description = "The ID of the main VPC."
  value       = aws_vpc.main.id
}

# UPDATED: Action 3 - Outputting a map is more flexible for consumers.
output "private_subnet_ids" {
  description = "A map of private subnet IDs, keyed by Availability Zone."
  value       = { for subnet in aws_subnet.private : subnet.availability_zone => subnet.id }
}

# UPDATED: Action 3
output "public_subnet_ids" {
  description = "A map of public subnet IDs, keyed by Availability Zone."
  value       = { for subnet in aws_subnet.public : subnet.availability_zone => subnet.id }
}
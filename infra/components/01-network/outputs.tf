# components/01-network/outputs.tf

output "vpc_id" {
  description = "The ID of the main VPC."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "A list of the private subnet IDs."
  value       = [for s in aws_subnet.private : s.id]
}

output "public_subnet_ids" {
  description = "A list of public subnet IDs, required for the mock ALB."
  value       = [for s in aws_subnet.public : s.id]
}
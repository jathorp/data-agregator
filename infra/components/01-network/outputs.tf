# Outputs are kept minimal to reduce coupling.
# We only output what other components absolutely need to know.

output "vpc_id" {
  description = "The ID of the main VPC."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "A list of the private subnet IDs."
  value       = [aws_subnet.private.id]
}
# modules/mock_nifi_endpoint/outputs.tf

output "endpoint_dns_name" {
  description = "The internal DNS name of the mock NiFi endpoint's ALB."
  value       = aws_lb.mock_nifi.dns_name
}

output "endpoint_security_group_id" {
  description = "The Security Group ID of the mock endpoint's ALB."
  value       = aws_security_group.alb_sg.id
}
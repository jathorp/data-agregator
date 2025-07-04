# components/04-observability/outputs.tf

output "alerting_sns_topic_arn" {
  description = "The ARN of the SNS topic for alerts."
  value       = aws_sns_topic.alerts.arn
}
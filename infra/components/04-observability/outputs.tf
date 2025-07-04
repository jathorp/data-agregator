# components/04-observability/outputs.tf

output "alerts_warning_sns_topic_arn" {
  description = "The ARN of the SNS topic for WARNING level alerts."
  value       = aws_sns_topic.alerts_warning.arn
}

output "alerts_critical_sns_topic_arn" {
  description = "The ARN of the SNS topic for CRITICAL level alerts."
  value       = aws_sns_topic.alerts_critical.arn
}
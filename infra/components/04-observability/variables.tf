# components/04-observability/variables.tf

variable "project_name" {
  type = string
}

variable "environment_name" {
  type = string
}

variable "alerting_sns_topic_name" {
  description = "The name of the SNS topic to send CloudWatch alerts to."
  type        = string
}
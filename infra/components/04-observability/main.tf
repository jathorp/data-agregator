# components/04-observability/main.tf

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# --- SNS Topics for Alerts ---
resource "aws_sns_topic" "alerts_warning" {
  name = "${var.project_name}-alerts-warning"
  tags = local.common_tags
}

resource "aws_sns_topic" "alerts_critical" {
  name = "${var.project_name}-alerts-critical"
  tags = local.common_tags
}

# --- CloudWatch Alarms ---

# 1. Alarm for messages in the Dead-Letter Queue (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project_name}-dlq-messages-visible"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "CRITICAL: Messages are in the DLQ. Manual intervention is required."
  alarm_actions       = [aws_sns_topic.alerts_critical.arn] # Point to critical topic
  ok_actions          = [aws_sns_topic.alerts_critical.arn]

  dimensions = {
    QueueName = data.terraform_remote_state.stateful.outputs.dlq_name
  }
}

# 2. Alarm for high number of Lambda errors (WARNING)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project_name}-lambda-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2 # Evaluate over 2 periods to avoid flapping
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "WARNING: The aggregator Lambda has 5 or more errors in a 10-minute period."
  alarm_actions       = [aws_sns_topic.alerts_warning.arn] # Point to warning topic
  ok_actions          = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    FunctionName = data.terraform_remote_state.application.outputs.lambda_function_name
  }
}

# 3. Alarm for SQS queue depth (aging messages) (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name          = "${var.project_name}-queue-age"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "5"
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = "60"
  statistic           = "Maximum"
  threshold           = "3600" # 1 hour
  alarm_description   = "CRITICAL: The oldest message in the queue is over 1 hour old, indicating a processing backlog."
  alarm_actions       = [aws_sns_topic.alerts_critical.arn] # Point to critical topic
  ok_actions          = [aws_sns_topic.alerts_critical.arn]

  dimensions = {
    QueueName = data.terraform_remote_state.stateful.outputs.main_queue_name
  }
}

# 4. NEW: Composite Alarm for a confirmed processing outage (CRITICAL)
resource "aws_cloudwatch_composite_alarm" "pipeline_outage" {
  alarm_name = "${var.project_name}-pipeline-outage-critical"

  # This alarm rule says: "Fire if the queue age alarm is triggered AND the lambda error alarm is triggered"
  alarm_rule = "ALARM(\"${aws_cloudwatch_metric_alarm.queue_age.alarm_name}\") AND ALARM(\"${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}\")"

  alarm_description = "CRITICAL OUTAGE: Pipeline backlog is growing and the Lambda is consistently failing. The system is down."
  actions_enabled   = true
  alarm_actions     = [aws_sns_topic.alerts_critical.arn]
  ok_actions        = [aws_sns_topic.alerts_critical.arn]

  tags = local.common_tags
}

# 5. NEW: Anomaly Detection for "Denial-of-Wallet" Protection (WARNING)
resource "aws_cloudwatch_metric_alarm" "sqs_inbound_anomaly" {
  alarm_name          = "${var.project_name}-sqs-inbound-anomaly"
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 2
  alarm_description   = "WARNING: An anomalous spike in incoming S3 files has been detected. Check for misconfigured clients or unexpected costs."

  metric_query {
    id = "m1"
    metric {
      metric_name = "NumberOfMessagesSent"
      namespace   = "AWS/SQS"
      period      = 600 # 10 minutes
      stat        = "Sum"
      dimensions = {
        QueueName = data.terraform_remote_state.stateful.outputs.main_queue_name
      }
    }
  }

  metric_query {
    id         = "e1"
    expression = "ANOMALY_DETECTION_BAND(m1, 2)" # A standard deviation of 2 is a good starting point
    label      = "NumberOfMessagesSent (Expected)"
  }

  alarm_actions = [aws_sns_topic.alerts_warning.arn]
  ok_actions    = [aws_sns_topic.alerts_warning.arn]

  tags = local.common_tags
}
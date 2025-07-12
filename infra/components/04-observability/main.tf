locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# --- SNS Topics for Alerts ---
resource "aws_sns_topic" "alerts_warning" {
  name = "${var.project_name}-alerts-warning-${var.environment_name}"
  tags = local.common_tags
}

resource "aws_sns_topic" "alerts_critical" {
  name = "${var.project_name}-alerts-critical-${var.environment_name}"
  tags = local.common_tags
}

# --- CloudWatch Alarms ---

# 1. DLQ Messages Visible (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project_name}-dlq-messages-visible-critical"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "CRITICAL: Messages are in the DLQ. Manual intervention is required."
  alarm_actions       = [aws_sns_topic.alerts_critical.arn]
  ok_actions          = [aws_sns_topic.alerts_critical.arn]
  dimensions = {
    QueueName = data.terraform_remote_state.stateful.outputs.dlq_name
  }
}

# 2. Lambda Errors (WARNING)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project_name}-lambda-errors-warning"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "WARNING: The aggregator Lambda has 5 or more errors in a 10-minute period."
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]
  ok_actions          = [aws_sns_topic.alerts_warning.arn]
  dimensions = {
    FunctionName = data.terraform_remote_state.application.outputs.lambda_function_name
  }
}

# 3. SQS Queue Age (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name          = "${var.project_name}-queue-age-critical"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 3600 # 1 hour
  alarm_description   = "CRITICAL: The oldest message in the queue is over 1 hour old, indicating a processing backlog."
  alarm_actions       = [aws_sns_topic.alerts_critical.arn]
  ok_actions          = [aws_sns_topic.alerts_critical.arn]
  dimensions = {
    QueueName = data.terraform_remote_state.stateful.outputs.main_queue_name
  }
}

# 4. Composite Alarm for Confirmed Outage (CRITICAL)
resource "aws_cloudwatch_composite_alarm" "pipeline_outage" {
  alarm_name        = "${var.project_name}-pipeline-outage-critical"
  alarm_rule        = "ALARM(\"${aws_cloudwatch_metric_alarm.queue_age.alarm_name}\") AND ALARM(\"${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}\")"
  alarm_description = "CRITICAL OUTAGE: Pipeline backlog is growing AND the Lambda is consistently failing. The system is down."
  actions_enabled   = true
  alarm_actions     = [aws_sns_topic.alerts_critical.arn]
  ok_actions        = [aws_sns_topic.alerts_critical.arn]
  tags              = local.common_tags
}

# 5. SQS Anomaly Detection (WARNING)
resource "aws_cloudwatch_metric_alarm" "sqs_inbound_anomaly" {
  alarm_name          = "${var.project_name}-sqs-inbound-anomaly-warning"
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 2
  threshold_metric_id = "e1"
  alarm_description   = "WARNING: Anomalous spike in SQS messages detected. Possible upstream issue or unexpected traffic."
  metric_query {
    id          = "m1"
    return_data = true
    metric {
      metric_name = "NumberOfMessagesSent"
      namespace   = "AWS/SQS"
      period      = 600
      stat        = "Sum"
      dimensions = {
        QueueName = data.terraform_remote_state.stateful.outputs.main_queue_name
      }
    }
  }
  metric_query {
    id          = "e1"
    expression  = "ANOMALY_DETECTION_BAND(m1, 2)"
    label       = "Expected range (±2σ)"
    return_data = true
  }
  alarm_actions = [aws_sns_topic.alerts_warning.arn]
  ok_actions    = [aws_sns_topic.alerts_warning.arn]
  tags          = local.common_tags
}

# 6. Distribution Bucket Size (WARNING) - Monitors for consumer failure
resource "aws_cloudwatch_metric_alarm" "distribution_bucket_size" {
  alarm_name          = "${var.project_name}-distribution-bucket-size-warning"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "NumberOfObjects"
  namespace           = "AWS/S3"
  period              = 3600 # Check once per hour
  statistic           = "Average"
  threshold           = 1000 # Example: Alarm if >1000 files accumulate over 3 hours
  alarm_description   = "WARNING: Files are accumulating in the distribution bucket, indicating the on-premise consumer may be down or failing."
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]
  ok_actions          = [aws_sns_topic.alerts_warning.arn]
  dimensions = {
    BucketName  = data.terraform_remote_state.stateful.outputs.distribution_bucket_id
    StorageType = "AllStorageTypes"
  }
}

# --- CloudWatch Dashboard ---
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-Pipeline-Health-${var.environment_name}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          metrics = [
            [
              "AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName",
              data.terraform_remote_state.stateful.outputs.main_queue_name,
              { label = "Main Queue" }
            ]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          stat    = "Maximum"
          period  = 300
          title   = "SQS Message Age (Backlog Indicator)"
          yAxis   = { left = { min = 0, label = "Seconds" } }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            [
              "AWS/Lambda", "Invocations", "FunctionName",
              data.terraform_remote_state.application.outputs.lambda_function_name,
              { stat = "Sum" }
            ],
            [
              "...", { stat = "Average", label = "Duration (Avg)" }
            ],
            [
              "AWS/Lambda", "Errors", "FunctionName",
              data.terraform_remote_state.application.outputs.lambda_function_name,
              { stat = "Sum", yAxis = "right" }
            ]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Lambda Performance & Errors"
          yAxis   = { right = { min = 0, label = "Error Count" } }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            [
              "AWS/S3", "NumberOfObjects", "BucketName",
              data.terraform_remote_state.stateful.outputs.distribution_bucket_id,
              "StorageType", "AllStorageTypes",
              { label = "Distribution Bucket" }
            ],
            [
              "...", "BucketName",
              data.terraform_remote_state.stateful.outputs.landing_bucket_id, ".", ".",
              { label = "Landing Bucket" }
            ]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          stat    = "Average"
          period  = 3600
          title   = "Bucket Object Counts (Consumer Health)"
          yAxis   = { left = { min = 0 } }
        }
      }
    ]
  })
}

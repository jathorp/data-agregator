# Observability Component (04-observability)

This Terraform component deploys comprehensive monitoring and alerting infrastructure for the data aggregator pipeline. It provides proactive monitoring of system health, performance metrics, and automated alerting for operational issues.

## Architecture Overview

The observability component creates:

- **SNS Topics**: Separate channels for WARNING and CRITICAL alerts
- **CloudWatch Alarms**: Automated monitoring of key system metrics
- **Composite Alarms**: Complex alerting logic combining multiple conditions
- **CloudWatch Dashboard**: Visual monitoring interface for operational teams

## Resources Created

### SNS Topics
- **Warning Topic** (`aws_sns_topic.alerts_warning`): Non-urgent operational alerts
- **Critical Topic** (`aws_sns_topic.alerts_critical`): Urgent alerts requiring immediate attention

### CloudWatch Alarms

#### 1. DLQ Messages Alarm (CRITICAL)
- **Metric**: `ApproximateNumberOfMessagesVisible` on Dead Letter Queue
- **Threshold**: ≥ 1 message
- **Purpose**: Detects failed message processing requiring manual intervention
- **Evaluation**: 1 period of 60 seconds

#### 2. Lambda Errors Alarm (WARNING)
- **Metric**: `Errors` on aggregator Lambda function
- **Threshold**: ≥ 5 errors in 10 minutes
- **Purpose**: Identifies Lambda function reliability issues
- **Evaluation**: 2 periods of 300 seconds

#### 3. SQS Queue Age Alarm (CRITICAL)
- **Metric**: `ApproximateAgeOfOldestMessage` on main queue
- **Threshold**: ≥ 3600 seconds (1 hour)
- **Purpose**: Detects processing backlogs and system slowdowns
- **Evaluation**: 5 periods of 60 seconds

#### 4. Pipeline Outage Composite Alarm (CRITICAL)
- **Logic**: Queue Age AND Lambda Errors both in alarm state
- **Purpose**: Confirms complete system outage requiring immediate response
- **Combines**: Queue backlog growth with consistent Lambda failures

#### 5. SQS Inbound Anomaly Alarm (WARNING)
- **Metric**: `NumberOfMessagesSent` with anomaly detection
- **Threshold**: Upper threshold (±2σ from expected pattern)
- **Purpose**: Detects unusual traffic spikes or upstream issues
- **Evaluation**: 2 periods of 600 seconds

#### 6. Distribution Bucket Size Alarm (WARNING)
- **Metric**: `NumberOfObjects` in distribution bucket
- **Threshold**: ≥ 1000 objects over 3 hours
- **Purpose**: Monitors downstream consumer health
- **Evaluation**: 3 periods of 3600 seconds

### CloudWatch Dashboard
Interactive dashboard displaying:
- **SQS Message Age**: Real-time backlog monitoring
- **Lambda Performance**: Invocations, duration, and error rates
- **Bucket Object Counts**: Landing and distribution bucket health
- **Consumer Health**: Distribution bucket accumulation trends

## Alert Severity Levels

### WARNING Alerts
- Lambda function errors (5+ in 10 minutes)
- Anomalous message traffic patterns
- Distribution bucket accumulation (consumer issues)
- **Response Time**: Within business hours
- **Impact**: Degraded performance, potential future issues

### CRITICAL Alerts
- Any messages in Dead Letter Queue
- Processing backlog over 1 hour
- Complete pipeline outage (composite alarm)
- **Response Time**: Immediate (24/7)
- **Impact**: System failure, data processing stopped

## Input Variables

### Required Variables
- `project_name`: Project identifier for resource naming and tagging
- `environment_name`: Environment identifier (dev, staging, prod)
- `aws_region`: AWS region for CloudWatch resources
- `remote_state_bucket`: S3 bucket storing Terraform remote state

## Outputs

- `alerts_warning_sns_topic_arn`: ARN for WARNING level alert subscriptions
- `alerts_critical_sns_topic_arn`: ARN for CRITICAL level alert subscriptions

## Dependencies

This component depends on outputs from:

1. **02-stateful-resources**:
   - DLQ name for dead letter queue monitoring
   - Main queue name for backlog monitoring
   - Distribution and landing bucket IDs for storage monitoring

2. **03-application**:
   - Lambda function name for performance monitoring

## Deployment

### Prerequisites
1. Deploy `02-stateful-resources` component first
2. Deploy `03-application` component second
3. Configure backend state storage

### Deploy Command
```bash
cd infra/components/04-observability
terraform init -backend-config="../../environments/${ENV}/04-observability.backend.tfvars"
terraform plan -var-file="../../environments/${ENV}/common.tfvars" \
               -var-file="../../environments/${ENV}/observability.tfvars"
terraform apply -var-file="../../environments/${ENV}/common.tfvars" \
                -var-file="../../environments/${ENV}/observability.tfvars"
```

### Environment Configuration Files
- `common.tfvars`: Shared variables (project_name, environment_name, etc.)
- `observability.tfvars`: Component-specific variables (if any)
- `04-observability.backend.tfvars`: Terraform backend configuration

## Alert Configuration

### SNS Topic Subscriptions
After deployment, configure SNS topic subscriptions:

```bash
# Subscribe email to WARNING alerts
aws sns subscribe \
  --topic-arn $(terraform output -raw alerts_warning_sns_topic_arn) \
  --protocol email \
  --notification-endpoint ops-team@company.com

# Subscribe email/SMS to CRITICAL alerts
aws sns subscribe \
  --topic-arn $(terraform output -raw alerts_critical_sns_topic_arn) \
  --protocol email \
  --notification-endpoint oncall@company.com

# Subscribe to PagerDuty/Slack for CRITICAL alerts
aws sns subscribe \
  --topic-arn $(terraform output -raw alerts_critical_sns_topic_arn) \
  --protocol https \
  --notification-endpoint https://events.pagerduty.com/integration/...
```

### Alarm Threshold Tuning
Adjust thresholds based on operational experience:

- **Lambda Errors**: Start with 5 errors/10min, adjust based on normal error rates
- **Queue Age**: 1 hour threshold works for most workloads, reduce for time-sensitive data
- **Bucket Size**: 1000 objects threshold depends on consumer processing rate
- **Anomaly Detection**: 2σ provides good balance between sensitivity and false positives

## Monitoring Best Practices

### Dashboard Usage
- **Real-time Monitoring**: Use dashboard for active incident response
- **Trend Analysis**: Review historical patterns for capacity planning
- **Performance Optimization**: Monitor Lambda duration for right-sizing

### Alert Response Procedures

#### WARNING Alerts
1. **Lambda Errors**: Check CloudWatch logs for error patterns
2. **Traffic Anomalies**: Verify upstream systems and data sources
3. **Consumer Issues**: Contact downstream teams, check distribution bucket

#### CRITICAL Alerts
1. **DLQ Messages**: Immediate investigation required, check message content
2. **Queue Backlog**: Scale Lambda concurrency or investigate performance issues
3. **Pipeline Outage**: Full system health check, escalate to engineering team

### Operational Metrics

Monitor these key performance indicators:
- **Processing Latency**: Queue age trends
- **Error Rate**: Lambda error percentage
- **Throughput**: Messages processed per hour
- **Consumer Health**: Distribution bucket growth rate

## Troubleshooting

### Common Issues

**False Positive Alerts**
- Review alarm thresholds and evaluation periods
- Check for expected traffic patterns (batch jobs, scheduled loads)
- Adjust anomaly detection sensitivity if needed

**Missing Alerts**
- Verify SNS topic subscriptions are confirmed
- Check CloudWatch alarm states and metric availability
- Validate IAM permissions for CloudWatch and SNS

**Dashboard Not Loading**
- Confirm all referenced resources exist in remote state
- Verify AWS region consistency across components
- Check CloudWatch service availability

### Alert Fatigue Prevention
- Use composite alarms to reduce noise
- Implement proper alert severity levels
- Regular review and tuning of thresholds
- Suppress alerts during planned maintenance

## Cost Optimization

### CloudWatch Costs
- **Alarms**: $0.10 per alarm per month
- **Dashboard**: $3.00 per dashboard per month
- **Metrics**: Most AWS service metrics are free
- **Custom Metrics**: $0.30 per metric per month (if added)

### Cost Management
- Review unused alarms quarterly
- Consolidate similar alerts where possible
- Use composite alarms to reduce individual alarm count
- Monitor CloudWatch usage in AWS Cost Explorer

## Security Considerations

### SNS Topic Security
- Topics are not publicly accessible by default
- Use IAM policies to control subscription access
- Enable server-side encryption for sensitive alert content
- Audit topic subscriptions regularly

### CloudWatch Security
- Alarms and dashboards inherit IAM permissions
- Use least-privilege access for monitoring roles
- Enable CloudTrail logging for audit trails
- Protect against metric manipulation

## Architecture Decisions

### Two-Tier Alert System
Separates WARNING and CRITICAL alerts to enable different response procedures and notification channels, reducing alert fatigue while ensuring urgent issues get immediate attention.

### Composite Alarm Strategy
Uses composite alarms to confirm true outages by requiring multiple failure conditions, reducing false positives from transient issues.

### Anomaly Detection
Leverages CloudWatch's machine learning-based anomaly detection for traffic pattern monitoring, automatically adapting to seasonal and growth trends.

### Consumer Health Monitoring
Monitors distribution bucket size as a proxy for downstream consumer health, providing early warning of integration issues outside the AWS environment.

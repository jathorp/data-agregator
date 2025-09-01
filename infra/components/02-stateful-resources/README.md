# Component: 02-Stateful-Resources

This Terraform component provisions all the stateful resources required for the Data Aggregation Pipeline. It creates S3 buckets, SQS queues, DynamoDB tables, and configures S3 replication for the pull-based architecture.

## Key Features & Design Decisions

This component implements the core stateful infrastructure with a focus on durability, security, and cost optimization.

### 1. Three-Bucket Architecture

**S3 Landing Bucket**
- **Purpose**: Secure ingestion point for external data uploads
- **Lifecycle**: Files expire after 7 days (configurable)
- **Security**: Enforces TLS-only access, blocks all public access
- **Versioning**: Enabled for data integrity

**S3 Distribution Bucket**
- **Purpose**: Staging area for bundles to be pulled by on-premise service
- **Lifecycle**: Files expire after 14 days if not consumed
- **Replication**: Automatically replicates to Archive bucket
- **Security**: Enforces TLS-only access, blocks all public access

**S3 Archive Bucket**
- **Purpose**: Long-term storage of processed bundles
- **Lifecycle**: Transitions to Deep Archive after 30 days
- **Versioning**: Enabled with lifecycle management
- **Security**: Enforces TLS-only access, blocks all public access

### 2. S3 Same-Region Replication (SRR)

- **Source**: Distribution Bucket → Archive Bucket
- **Benefits**: More resilient than dual-write in Lambda code
- **Configuration**: Replicates all objects, excludes delete markers
- **IAM**: Dedicated replication role with least-privilege permissions

### 3. Event-Driven Processing

**SQS Main Queue**
- **Purpose**: Decouples S3 events from Lambda processing
- **Configuration**: 4-day message retention, 200s visibility timeout
- **Dead Letter Queue**: 5 retry attempts before moving to DLQ
- **Security**: Server-side encryption enabled

**S3 Event Notifications**
- **Trigger**: `s3:ObjectCreated:*` events from Landing Bucket
- **Target**: SQS Main Queue
- **Filter**: Configurable prefix filtering

### 4. Idempotency Management

**DynamoDB Table**
- **Purpose**: Stores idempotency keys for exactly-once processing
- **Configuration**: Pay-per-request billing, TTL enabled
- **Security**: Server-side encryption, point-in-time recovery
- **Key Schema**: Single hash key `object_key` (String)

### 5. Security & Compliance

**Encryption at Rest**
- **S3**: AES-256 server-side encryption
- **SQS**: AWS managed server-side encryption
- **DynamoDB**: AWS managed server-side encryption

**Access Logging**
- **S3 Access Logs**: Dedicated bucket with 90-day lifecycle
- **Bucket Logging**: All buckets log access to central location

## Input Variables

| Name                           | Description                                                    | Type     | Required |
|:-------------------------------|:---------------------------------------------------------------|:---------|:---------|
| `project_name`                 | The name of the project                                        | `string` | Yes      |
| `environment_name`             | The name of the environment (e.g., dev, prod)                 | `string` | Yes      |
| `landing_bucket_name`          | Name for the S3 landing bucket                                 | `string` | Yes      |
| `distribution_bucket_name`     | Name for the S3 distribution bucket                            | `string` | Yes      |
| `archive_bucket_name`          | Name for the S3 archive bucket                                 | `string` | Yes      |
| `main_queue_name`              | Name for the main SQS queue                                    | `string` | Yes      |
| `dlq_name`                     | Name for the dead letter queue                                 | `string` | Yes      |
| `idempotency_table_name`       | Name for the DynamoDB idempotency table                        | `string` | Yes      |
| `lambda_role_name`             | Name for the Lambda execution role                             | `string` | Yes      |
| `s3_event_notification_prefix` | Prefix filter for S3 event notifications                       | `string` | No       |

## Outputs

| Name                        | Description                                    |
|:----------------------------|:-----------------------------------------------|
| `landing_bucket_id`         | ID of the landing S3 bucket                   |
| `landing_bucket_arn`        | ARN of the landing S3 bucket                  |
| `distribution_bucket_id`    | ID of the distribution S3 bucket              |
| `distribution_bucket_arn`   | ARN of the distribution S3 bucket             |
| `archive_bucket_id`         | ID of the archive S3 bucket                   |
| `archive_bucket_arn`        | ARN of the archive S3 bucket                  |
| `main_queue_arn`            | ARN of the main SQS queue                     |
| `main_queue_url`            | URL of the main SQS queue                     |
| `dlq_arn`                   | ARN of the dead letter queue                  |
| `idempotency_table_name`    | Name of the DynamoDB idempotency table        |
| `idempotency_table_arn`     | ARN of the DynamoDB idempotency table         |
| `lambda_iam_role_name`      | Name of the Lambda execution role             |
| `lambda_iam_role_arn`       | ARN of the Lambda execution role              |

## Deployment Instructions

### Prerequisites

- Terraform CLI is installed
- AWS CLI is configured with appropriate credentials
- Network component (01-network) must be deployed first

### Step 1: Navigate to Component Directory

```bash
cd infra/components/02-stateful-resources
```

### Step 2: Initialize Terraform

```bash
terraform init -backend-config="../../environments/dev/02-stateful-resources.backend.tfvars"
```

### Step 3: Plan and Apply

```bash
# Plan the deployment
terraform plan -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/stateful-resources.tfvars"

# Apply the changes
terraform apply -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/stateful-resources.tfvars"
```

## Important Notes

### S3 Replication Considerations

- Replication is eventually consistent
- Delete markers are not replicated (by design)
- Cross-region replication incurs data transfer costs (not applicable for SRR)

### Cost Optimization

- S3 lifecycle policies automatically transition data to cheaper storage classes
- DynamoDB uses on-demand billing to avoid over-provisioning
- SQS message retention is optimized for the expected processing time

### Security Best Practices

- All buckets block public access by default
- Bucket policies enforce TLS-only access
- IAM roles follow principle of least privilege
- Server-side encryption is enabled for all resources

## Troubleshooting

### Common Issues

**S3 Replication Not Working**
- Check replication role permissions
- Verify source bucket versioning is enabled
- Check CloudWatch metrics for replication failures

**SQS Messages Not Being Delivered**
- Verify S3 event notification configuration
- Check SQS queue policy allows S3 to send messages
- Ensure message retention period is sufficient

**DynamoDB Access Issues**
- Verify Lambda role has required DynamoDB permissions
- Check if table exists and is in ACTIVE state
- Verify TTL configuration if using time-based expiration

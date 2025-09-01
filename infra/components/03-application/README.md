# Application Component (03-application)

This Terraform component deploys the core data aggregator Lambda function and its associated resources. The Lambda function implements a pull-based architecture that processes files from the landing bucket and creates aggregated bundles in the distribution bucket.

## Architecture Overview

The application component creates:

- **Lambda Function**: The main data aggregator that processes files from S3
- **IAM Policy**: Least-privilege permissions for the Lambda function
- **Security Group**: Network access controls for VPC-deployed Lambda
- **SQS Event Source Mapping**: Triggers Lambda execution from queue messages

## Resources Created

### Lambda Function (`aws_lambda_function.aggregator`)
- **Runtime**: Python 3.12 on ARM64 architecture
- **Memory**: 512 MB (configurable)
- **Timeout**: 180 seconds (configurable)
- **Ephemeral Storage**: 2 GB (configurable)
- **Concurrency**: Limited to 10 concurrent executions
- **VPC Configuration**: Deployed in private subnets with security group
- **Handler**: `data_aggregator.app.handler`

### IAM Policy (`aws_iam_policy.aggregator_lambda_policy`)
Grants minimal required permissions:
- **CloudWatch Logs**: Create log groups, streams, and put log events
- **SQS**: Receive, delete messages, and get queue attributes
- **S3 Landing Bucket**: Read objects and list bucket contents
- **S3 Distribution Bucket**: Write aggregated bundle objects
- **DynamoDB**: Full access to idempotency table for duplicate detection
- **VPC**: Create/describe/delete network interfaces for VPC deployment

### Security Group (`aws_security_group.aggregator_lambda_sg`)
Implements least-privilege network access:
- **S3 Gateway Endpoint**: HTTPS (443) access via prefix list
- **DynamoDB Gateway Endpoint**: HTTPS (443) access via prefix list  
- **VPC Interface Endpoints**: HTTPS (443) access for SQS and KMS within VPC CIDR

### SQS Event Source Mapping (`aws_lambda_event_source_mapping.sqs_trigger`)
- **Batch Size**: 100 messages per invocation
- **Batching Window**: 15 seconds maximum wait time
- **Error Handling**: Reports batch item failures for partial batch processing

## Environment Variables

The Lambda function receives these environment variables:

| Variable | Description | Source |
|----------|-------------|---------|
| `DISTRIBUTION_BUCKET_NAME` | Target bucket for aggregated bundles | Stateful resources output |
| `IDEMPOTENCY_TABLE_NAME` | DynamoDB table for duplicate detection | Stateful resources output |
| `LOG_LEVEL` | Powertools logger level (INFO, DEBUG, etc.) | Variable (default: INFO) |
| `IDEMPOTENCY_TTL_DAYS` | Days to retain idempotency keys | Variable (default: 7) |
| `MAX_BUNDLE_INPUT_MB` | Maximum input size per bundle in MB | Variable (default: 100) |
| `SERVICE_NAME` | Service name for observability | Project name variable |
| `ENVIRONMENT` | Environment name for observability | Environment variable |

## Input Variables

### Required Variables
- `project_name`: Project identifier for resource naming and tagging
- `environment_name`: Environment identifier (dev, staging, prod)
- `remote_state_bucket`: S3 bucket storing Terraform remote state
- `aws_region`: AWS region for deployment
- `lambda_artifacts_bucket_name`: S3 bucket containing Lambda deployment package
- `lambda_s3_key`: Object key for Lambda ZIP file in artifacts bucket
- `lambda_function_name`: Name for the Lambda function resource

### Optional Variables
- `lambda_handler`: Function handler (default: "app.handler")
- `lambda_runtime`: Python runtime version (default: "python3.12")
- `lambda_timeout`: Execution timeout in seconds (default: 180)
- `lambda_memory_size`: Memory allocation in MB (default: 512)
- `lambda_ephemeral_storage_size`: /tmp directory size in MB (default: 2048)
- `idempotency_ttl_days`: DynamoDB TTL for idempotency keys (default: 7)
- `log_level`: Powertools logger level (default: "INFO")
- `max_bundle_input_mb`: Maximum input file size per bundle (default: 100)

## Outputs

- `lambda_function_name`: The deployed Lambda function name
- `lambda_function_arn`: The Lambda function ARN for cross-component references

## Dependencies

This component depends on outputs from:

1. **01-network**: VPC ID, private subnet IDs, and VPC CIDR block
2. **02-stateful-resources**: 
   - S3 bucket ARNs and IDs (landing, distribution)
   - SQS queue ARN for event source mapping
   - DynamoDB table ARN and name for idempotency
   - Lambda IAM role ARN and name

## Deployment

### Prerequisites
1. Deploy `01-network` component first
2. Deploy `02-stateful-resources` component second
3. Upload Lambda deployment package to artifacts S3 bucket
4. Configure backend state storage

### Deploy Command
```bash
cd infra/components/03-application
terraform init -backend-config="../../environments/${ENV}/03-application.backend.tfvars"
terraform plan -var-file="../../environments/${ENV}/common.tfvars" \
               -var-file="../../environments/${ENV}/application.tfvars"
terraform apply -var-file="../../environments/${ENV}/common.tfvars" \
                -var-file="../../environments/${ENV}/application.tfvars"
```

### Environment Configuration Files
- `common.tfvars`: Shared variables (project_name, environment_name, etc.)
- `application.tfvars`: Component-specific variables (Lambda configuration)
- `03-application.backend.tfvars`: Terraform backend configuration

## Security Considerations

### Network Security
- Lambda deployed in private subnets with no internet access
- Security group restricts outbound traffic to required AWS services only
- Uses VPC endpoints to avoid internet routing for AWS API calls

### IAM Security  
- Follows principle of least privilege
- Read-only access to landing bucket
- Write-only access to distribution bucket
- Scoped permissions to specific resources where possible

### Operational Security
- Reserved concurrency prevents runaway executions
- Timeout limits prevent hung processes
- Ephemeral storage sized appropriately for workload
- Environment variables avoid hardcoded secrets

## Troubleshooting

### Common Issues

**Lambda Function Not Triggering**
- Verify SQS queue has messages
- Check Lambda function logs in CloudWatch
- Confirm event source mapping is active
- Validate IAM permissions for SQS access

**Permission Denied Errors**
- Review IAM policy attachments
- Verify resource ARNs in policy statements
- Check VPC endpoint policies if using interface endpoints
- Confirm Lambda execution role trust relationship

**Network Connectivity Issues**
- Verify security group egress rules
- Check VPC endpoint configurations
- Confirm subnet routing tables
- Validate prefix list IDs for gateway endpoints

**Performance Issues**
- Monitor Lambda duration and memory usage
- Adjust memory allocation if needed
- Review ephemeral storage utilization
- Consider increasing timeout for large files

### Monitoring
- CloudWatch Logs: `/aws/lambda/${function_name}`
- CloudWatch Metrics: Lambda function metrics
- X-Ray Tracing: Enabled via Powertools (if configured in observability component)
- SQS Metrics: Queue depth, message age, processing rates

## Architecture Decisions

### VPC Deployment
The Lambda function is deployed within a VPC for enhanced security and network control, despite the additional complexity of managing ENIs and VPC endpoints.

### ARM64 Architecture
Uses ARM64 (Graviton2) processors for better price-performance compared to x86_64, with Python 3.12 runtime support.

### Reserved Concurrency
Limited to 10 concurrent executions to prevent overwhelming downstream systems and control costs while maintaining reasonable throughput.

### Security Group Design
Implements explicit egress rules using AWS prefix lists for gateway endpoints and VPC CIDR for interface endpoints, following network security best practices.

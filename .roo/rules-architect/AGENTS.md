# Deployment and Infrastructure Requirements

## Core Design Philosophy

- **Lambda-First Architecture**: The Python Lambda function is the permanent core; Terraform infrastructure serves as developer scaffolding that may evolve or be replaced
- **Cost Optimization Priority**: Every architectural decision prioritizes AWS cost efficiency over convenience
- **Modular Components**: Infrastructure designed to support code sharing across multiple Lambda functions

## Infrastructure Architecture

```
AWS Lambda (ARM64) → SQS → S3 Event Notifications
                  ↓
              DynamoDB (Idempotency)
                  ↓
              CloudWatch (Observability)
```

## Terraform Module Structure

```bash
infra/components/01-network/
├── main.tf          # VPC, subnets, security groups
├── outputs.tf       # Network resource references
└── tf.sh           # Environment-specific deployment script

infra/components/02-stateful-resources/
├── main.tf          # S3 buckets, DynamoDB tables, SQS queues
├── outputs.tf       # Resource ARNs and names
└── tf.sh           # Stateful resource deployment

infra/components/03-application/
├── main.tf          # Lambda function, IAM roles, event sources
├── outputs.tf       # Application endpoints and identifiers
└── tf.sh           # Application deployment

infra/components/04-observability/
├── main.tf          # CloudWatch dashboards, alarms, log groups
└── tf.sh           # Monitoring deployment
```

## Deployment Sequence

```bash
# 1. Build Lambda package (ARM64 architecture required)
./build.sh

# 2. Deploy infrastructure components in order
cd infra/components/01-network && ./tf.sh dev apply
cd infra/components/02-stateful-resources && ./tf.sh dev apply
cd infra/components/03-application && ./tf.sh dev apply
cd infra/components/04-observability && ./tf.sh dev apply

# 3. Verify deployment with E2E tests
cd e2e_tests && python main.py --config configs/config_00_singe_file.json
```

## Environment Configuration

```bash
# Environment-specific variables in tf.sh scripts
export TF_VAR_environment="dev"
export TF_VAR_lambda_zip_path="../../../dist/lambda.zip"
export AWS_REGION="us-east-1"
```

## Lambda Function Requirements (Cost-Optimized)

- **Runtime**: Python 3.13
- **Architecture**: ARM64 (Graviton2) - 20% cost savings over x86_64
- **Memory**: 512MB (matches SpooledTemporaryFile configuration) - Optimized for cost/performance ratio
- **Timeout**: Configurable via environment variables - Prevents runaway costs
- **Package**: Built via [`build.sh`](build.sh) script - ARM64-specific compilation
- **Provisioned Concurrency**: Avoided to minimize costs - Cold starts acceptable for batch processing

## Resource Dependencies

```
S3 Buckets → Lambda Event Sources → SQS Queues → Lambda Function
DynamoDB Tables → Lambda IAM Role → Lambda Function
VPC/Subnets → Lambda Function (if VPC deployment required)
```

## Monitoring and Observability

- **CloudWatch Logs**: Structured logging with safe context extraction
- **CloudWatch Metrics**: Custom metrics for processing rates and errors
- **CloudWatch Alarms**: Threshold-based alerting for failures and timeouts
- **X-Ray Tracing**: Distributed tracing for performance analysis

## Cost-Efficient Security

- **IAM Least Privilege**: Function-specific permissions for S3, DynamoDB, SQS - Reduces attack surface and potential costs from unauthorized usage
- **S3 Key Sanitization**: Automatic sanitization in schema validation - Prevents costly security incidents
- **VPC Isolation**: Optional VPC deployment - Only when required due to NAT Gateway costs
- **Encryption**: At-rest and in-transit encryption for all data stores - AWS managed keys to avoid KMS costs

## Infrastructure Evolution Strategy

- **Terraform as Scaffolding**: Current Terraform modules provide developer convenience but are not permanent
- **Lambda Function Portability**: Core Python code designed to work with any infrastructure provisioning method
- **Shared Component Library**: Infrastructure patterns designed for reuse across multiple Lambda deployments
- **Cost Monitoring**: CloudWatch billing alarms and cost allocation tags for all resources
# Component: 03-Application

This Terraform component is responsible for deploying the core application logic of the pipeline. It provisions the AWS Lambda function, its SQS trigger, and all the necessary configuration and security settings to allow it to run.

## Key Features & Design Decisions

This component is designed to be secure, efficient, and resilient.

### 1. Decoupled IAM Policy Attachment

*   **What:** This component does **not** create the Lambda's IAM Role. Instead, it looks up the role "shell" created by the `02-stateful-resources` component and attaches a specific, least-privilege IAM Policy to it.
*   **Why:** This is a critical architectural decision that resolves circular dependencies between infrastructure components. It allows for a clean, linear deployment workflow (`01-network` -> `02-stateful-resources` -> `03-application`).

### 2. Secure by Default Network Isolation

*   **What:** The Lambda function is deployed into the private subnets of the VPC and is associated with a dedicated Security Group that has **no egress rules**.
*   **Why:** This ensures the function is completely isolated from the internet and cannot initiate any outbound network connections. All communication with other AWS services (S3, SQS, DynamoDB) happens securely over private VPC Endpoints, which do not require security group egress rules. This aligns with a zero-trust security model.

### 3. Resilient SQS Trigger

*   **What:** The `aws_lambda_event_source_mapping` resource connects the SQS queue to the Lambda function. It is configured with a batch size of 100 and a 5-second batching window to balance latency and cost.
*   **Why:** Crucially, it enables the `ReportBatchItemFailures` feature. This allows the Lambda code to report partial failures within a batch, preventing a single "poison pill" message from blocking the entire pipeline and maximizing throughput (NFR-05).

### 4. Least-Privilege IAM Policy

*   **What:** The attached IAM policy grants the Lambda function only the exact permissions it needs to perform its job: read from the landing queue and bucket, write to the archive and distribution buckets, and manage records in the idempotency table.
*   **Why:** This adheres to the principle of least privilege, minimizing the potential impact of a security compromise.

## Input Variables

| Name                            | Description                                                                  | Type     | Required? |
|:--------------------------------|:-----------------------------------------------------------------------------|:---------|:----------|
| `project_name`                  | The name of the project.                                                     | `string` | Yes       |
| `environment_name`              | The name of the environment (e.g., dev, prod).                               | `string` | Yes       |
| `aws_region`                    | The AWS region to deploy resources into.                                     | `string` | Yes       |
| `lambda_artifacts_bucket_name`  | The name of the central S3 bucket for storing Lambda deployment packages.    | `string` | Yes       |
| `lambda_s3_key`                 | The object key for the Lambda deployment package in the artifacts S3 bucket. | `string` | Yes       |
| `lambda_function_name`          | The name of the Lambda function.                                             | `string` | Yes       |
| `lambda_handler`                | The handler for the Lambda function (e.g., 'app.handler').                   | `string` | No        |
| `lambda_runtime`                | The runtime for the Lambda function.                                         | `string` | No        |
| `lambda_timeout`                | The timeout in seconds for the Lambda function.                              | `number` | No        |
| `lambda_memory_size`            | The amount of memory in MB to allocate to the Lambda function.               | `number` | No        |
| `lambda_ephemeral_storage_size` | The size of the Lambda function's /tmp directory in MB.                      | `number` | No        |
| `idempotency_ttl_days`          | The number of days to retain the idempotency key in DynamoDB.                | `number` | No        |

## Outputs

| Name                   | Description                                 |
|:-----------------------|:--------------------------------------------|
| `lambda_function_name` | The name of the aggregator Lambda function. |
| `lambda_function_arn`  | The ARN of the aggregator Lambda function.  |

## Deployment Instructions

### Prerequisites

*   Terraform CLI is installed.
*   AWS CLI is installed and configured.
*   The `01-network` and `02-stateful-resources` components must be successfully deployed first.

### Deployment Steps

1.  **Navigate to Directory:** `cd components/03-application`
2.  **Initialize Terraform:**
    ```bash
    # Example for the 'dev' environment
    terraform init -backend-config="../../environments/dev/03-application.backend.tfvars"
    ```
3.  **Plan and Apply Changes:**
    ```bash
    # Example for the 'dev' environment
    terraform plan -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/application.tfvars"

    terraform apply -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/application.tfvars"
    ```
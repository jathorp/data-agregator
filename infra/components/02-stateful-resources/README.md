# Component: 02-Stateful Resources

This Terraform component provisions all the stateful resources required for the Data Aggregation Pipeline. It is responsible for creating the data stores, queues, and the foundational IAM Role that form the core of the pipeline's infrastructure.

## Key Features & Design Decisions

This component is built to a production-grade standard, focusing on security, resilience, and operational best practices.

### 1. Purpose-Built S3 Bucket Strategy

*   **What:** Three distinct S3 buckets are created, each with a specific role:
    *   `Landing Bucket`: A secure drop-zone for the external party with a short 7-day retention period.
    *   `Distribution Bucket`: A transient "mailbox" bucket for the on-premise service to pull finished data bundles from.
    *   `Archive Bucket`: A write-only, versioned, long-term archive with `prevent_destroy` enabled and a lifecycle policy to transition data to Glacier Deep Archive.
*   **Why:** This separation of concerns ensures data is managed according to its purpose, optimizing for security, cost, and operational clarity.

### 2. Secure Default Encryption

*   **What:** All data is encrypted at rest. S3 buckets use S3-Managed Keys (SSE-S3), SQS queues use SQS-Managed SSE, and DynamoDB tables use the default AWS-owned encryption.
*   **Why:** This provides a strong, maintenance-free security baseline, ensuring all data is encrypted without the overhead of managing KMS key policies for this use case (NFR-06).

### 3. Strict In-Transit Encryption (S3)

*   **What:** All three S3 buckets have a bucket policy that explicitly denies any API requests made over an insecure (non-HTTPS) connection.
*   **Why:** Guarantees data integrity and confidentiality for all data transfers to and from S3.

### 4. Data Resilience and Protection

*   **What:** The `archive` S3 bucket and the `idempotency` DynamoDB table are protected from accidental deletion with `prevent_destroy`. The DynamoDB table has Point-in-Time Recovery (PITR) enabled.
*   **Why:** Provides strong guardrails against accidental or catastrophic data loss.

### 5. Comprehensive Logging and Housekeeping

*   **What:** All access requests to the primary S3 buckets are logged to a central `access-logs` bucket. Lifecycle policies automatically clean up old raw files, old logs, and incomplete multipart uploads.
*   **Why:** Essential for security auditing, troubleshooting, and cost control.

### 6. Decoupled IAM Role for Compute

*   **What:** A foundational IAM Role "shell" for the application Lambda is created in this component. The role itself has no permissions attached here; it only establishes a trust relationship with the AWS Lambda service.
*   **Why:** This is a clean architectural pattern that separates the *creation of an identity* (this component) from the *granting of permissions* (the `03-application` component). This avoids dependency issues and aligns with the principle of separation of concerns.

## Input Variables

| Name                       | Description                                              | Type     | Required |
|:---------------------------|:---------------------------------------------------------|:---------|:---------|
| `project_name`             | The name of the project, used as a prefix for resources. | `string` | Yes      |
| `environment_name`         | The name of the environment (e.g., dev, prod).           | `string` | Yes      |
| `landing_bucket_name`      | The base name for the S3 landing bucket.                 | `string` | Yes      |
| `archive_bucket_name`      | The base name for the S3 archive bucket.                 | `string` | Yes      |
| `distribution_bucket_name` | The base name for the S3 distribution bucket.            | `string` | Yes      |
| `main_queue_name`          | The name for the main SQS queue.                         | `string` | Yes      |
| `dlq_name`                 | The name for the SQS Dead-Letter Queue.                  | `string` | Yes      |
| `idempotency_table_name`   | The name for the idempotency DynamoDB table.             | `string` | Yes      |
| `lambda_role_name`         | The name for the Lambda function's IAM role.             | `string` | Yes      |

## Outputs

This component produces numerous outputs, including the ARNs and names/IDs of all created S3 buckets, SQS queues, the DynamoDB table, and the Lambda IAM role. These outputs are consumed by downstream components.

## Deployment Instructions

### Prerequisites

*   Terraform CLI is installed.
*   AWS CLI is installed and configured.

### Deployment Steps

> [!NOTE]
> This component should be deployed **after** `01-network` and **before** `03-application`.

1.  **Navigate to Directory:** `cd components/02-stateful-resources`
2.  **Initialize Terraform:**
    ```bash
    # Example for the 'dev' environment
    terraform init -backend-config="../../environments/dev/02-stateful-resources.backend.tfvars"
    ```
3.  **Plan and Apply Changes:**
    ```bash
    # Example for the 'dev' environment
    terraform plan -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/stateful-resources.tfvars"

    terraform apply -var-file="../../environments/dev/common.tfvars" -var-file="../../environments/dev/stateful-resources.tfvars"
    ```
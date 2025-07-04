
# Component: 02-Stateful Resources

This Terraform component provisions all the stateful resources required for the Data Aggregation Pipeline. It is responsible for creating the data stores, queues, security principals, and the foundational IAM Role that form the core of the pipeline's infrastructure.

## Key Features & Design Decisions

This component is built to a production-grade standard, focusing on security, resilience, and operational best practices.

### 1. Decoupled IAM Role for Compute

*   **What:** A foundational IAM Role "shell" for the application Lambda is created in this component. The role itself has no permissions; it only trusts the AWS Lambda service.
*   **Why:** This is a critical architectural decision that **breaks circular dependencies**. It allows the KMS key policy to grant permissions to this role *before* the application component (which attaches the specific permissions policies) is ever deployed. This establishes a clean, linear `02-stateful -> 03-application` deployment flow.

### 2. Centralized Encryption with Customer-Managed KMS Key

*   **What:** A single, customer-managed AWS KMS Key is created with a strict, least-privilege policy. It is used to encrypt all S3 buckets, SQS queues, DynamoDB tables, and the Secrets Manager secret.
*   **Why:** This provides centralized control over data encryption, a clear audit trail, and ensures that only explicitly authorized principals (like the Lambda role) can access the encrypted data (NFR-06).

### 3. Strict In-Transit Encryption (S3)

*   **What:** Both the landing and archive S3 buckets have a bucket policy that explicitly denies any API requests made over an insecure (non-HTTPS) connection.
*   **Why:** Guarantees data integrity and confidentiality during transit.

### 4. Secure Secret Management

*   **What:** Creates a container for NiFi credentials in AWS Secrets Manager. Terraform **does not** manage the password itself.
*   **Why:** Prevents sensitive credentials from being stored in version control or Terraform state files.

### 5. Data Resilience and Protection

*   **What:** The archive S3 bucket and DynamoDB tables are protected from accidental deletion with `prevent_destroy`. DynamoDB tables have Point-in-Time Recovery (PITR) enabled.
*   **Why:** Provides strong guardrails against catastrophic data loss.

### 6. Comprehensive Logging and Housekeeping

*   **What:** All access requests to the primary S3 buckets are logged. Lifecycle policies automatically clean up old files and incomplete multipart uploads.
*   **Why:** Essential for security auditing, troubleshooting, and cost control.

## Input Variables

| Name                         | Description                                                                   | Type     | Required |
|------------------------------|-------------------------------------------------------------------------------|----------|:--------:|
| `project_name`               | ...                                                                           | `string` |   Yes    |
| `environment_name`           | ...                                                                           | `string` |   Yes    |
| `landing_bucket_name`        | ...                                                                           | `string` |   Yes    |
| `archive_bucket_name`        | ...                                                                           | `string` |   Yes    |
| `main_queue_name`            | ...                                                                           | `string` |   Yes    |
| `dlq_name`                   | ...                                                                           | `string` |   Yes    |
| `idempotency_table_name`     | ...                                                                           | `string` |   Yes    |
| `circuit_breaker_table_name` | ...                                                                           | `string` |   Yes    |
| `nifi_secret_name`           | ...                                                                           | `string` |   Yes    |
| `kms_admin_role_arn`         | ARN of the IAM role that will have administrative permissions on the KMS key. | `string` |   Yes    |
| `lambda_role_name`           | The name for the Lambda function's IAM role.                                  | `string` |   Yes    |

## Outputs

This component produces numerous outputs, including the ARNs and names of all created resources and the Lambda IAM role, which are consumed by downstream components.

## Deployment Instructions

### Prerequisites

*   Terraform CLI (`~> 1.6`) is installed.
*   AWS CLI is installed and configured.

### Deployment Steps

> [!NOTE]
> This component should be deployed **after** `01-network` and **before** `03-application`.

1.  **Navigate to Directory:** `cd components/02-stateful-resources`
2.  **Initialize Terraform:**
    ```bash
    terraform init -backend-config="../../environments/dev/backend.tfvars"
    ```
3.  **Plan and Apply Changes:**
    ```bash
    terraform plan -var-file="../../environments/dev/stateful.tfvars"
    terraform apply -var-file="../../environments/dev/stateful.tfvars"
    ```

### Post-Deployment: Populate Secret Value

> [!IMPORTANT]
> This is a **critical, one-time manual step** required after the initial deployment.

Run the following AWS CLI command, replacing the placeholders with your actual values.

```bash
aws secretsmanager put-secret-value \
  --secret-id "data-aggregator/nifi-credentials-dev" \
  --secret-string '{"username":"dev-user","password":"a-secure-dev-password-123!"}' \
  --region eu-west-2
```
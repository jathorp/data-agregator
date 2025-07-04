# Component: 03-Application

This Terraform component is responsible for deploying the core application logic of the pipeline. It provisions the AWS Lambda function, its trigger, and all the necessary configuration and security settings to allow it to run. It also includes a testing harness for non-production environments.

## Key Features & Design Decisions

This component is designed to be secure, environment-aware, and resilient.

### 1. Decoupled IAM Policy Attachment

*   **What:** This component does **not** create the Lambda's IAM Role. Instead, it looks up the role created by the `02-stateful-resources` component and attaches a specific, least-privilege IAM Policy to it.
*   **Why:** This is a critical architectural decision that resolves circular dependencies between infrastructure components. It allows for a clean, linear deployment workflow (`01-network` -> `02-stateful-resources` -> `03-application`).

### 2. Environment-Aware Deployment (`dev` vs. `prod`)

*   **What:** The component contains conditional logic that changes its behavior based on the `environment_name` variable:
    *   **Mock Endpoint:** For the `dev` environment, a mock NiFi endpoint (an internal Application Load Balancer) is automatically created for testing purposes. This resource is not created in `prod`.
    *   **Dynamic Egress:** The Lambda's Security Group rules are dynamic. In `dev`, it allows outbound traffic to the mock endpoint. In `prod`, it allows outbound traffic to the real on-premise NiFi CIDR block.
*   **Why:** This allows a single, clean codebase to manage multiple environments, making the infrastructure DRY (Don't Repeat Yourself) and easier to maintain.

### 3. Resilient SQS Trigger

*   **What:** The `aws_lambda_event_source_mapping` resource connects the SQS queue to the Lambda function. It is configured with a batch size of 100 and a 10-second batching window to balance latency and cost.
*   **Why:** Crucially, it enables the `ReportBatchItemFailures` feature. This allows the Lambda code to report partial failures within a batch, preventing a single bad message from blocking the entire pipeline and maximizing throughput (NFR-05).

### 4. Secure Network Placement

*   **What:** The Lambda function is deployed into the private subnets of the VPC and is associated with a dedicated Security Group.
*   **Why:** This ensures the function is not exposed to the internet. The Security Group acts as a stateful firewall, strictly controlling what the Lambda can communicate with (NFR-10).

## Input Variables

| Name                   | Description                                                               | Type     | Required |
|------------------------|---------------------------------------------------------------------------|----------|:--------:|
| `project_name`         | The name of the project.                                                  | `string` |   Yes    |
| `environment_name`     | The name of the environment (e.g., dev, prod).                            | `string` |   Yes    |
| `lambda_function_name` | The name of the Lambda function.                                          | `string` |   Yes    |
| `lambda_handler`       | The handler for the Lambda function (e.g., 'handler.lambda_handler').     | `string` |   Yes    |
| `lambda_runtime`       | The runtime for the Lambda function (e.g., 'python3.13').                 | `string` |   Yes    |
| `lambda_timeout`       | The timeout in seconds for the Lambda function.                           | `number` |    No    |
| `lambda_memory_size`   | The amount of memory in MB to allocate to the Lambda function.            | `number` |    No    |
| `nifi_endpoint_url`    | The full HTTPS URL for the on-premise NiFi ingest endpoint. *(Prod only)* | `string` |    No    |
| `nifi_endpoint_cidr`   | The IP/CIDR block of the on-premise NiFi endpoint. *(Prod only)*          | `string` |    No    |

## Outputs

| Name                   | Description                                 |
|------------------------|---------------------------------------------|
| `lambda_function_name` | The name of the aggregator Lambda function. |
| `lambda_function_arn`  | The ARN of the aggregator Lambda function.  |

## Deployment Instructions

### Prerequisites

*   Terraform CLI (`~> 1.6`) is installed.
*   AWS CLI is installed and configured.
*   The `01-network` and `02-stateful-resources` components must be successfully deployed first.

### Deployment Steps

1.  **Navigate to Directory:** `cd components/03-application`
2.  **Initialize Terraform:**
    ```bash
    terraform init -backend-config="../../environments/dev/backend.tfvars"
    ```
3.  **Plan and Apply Changes:**
    ```bash
    terraform plan -var-file="../../environments/dev/application.tfvars"
    terraform apply -var-file="../../environments/dev/application.tfvars"
    ```
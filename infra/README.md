# Real-Time Data Aggregation Pipeline

This repository contains the complete Infrastructure as Code (IaC) for a real-time data ingestion and aggregation pipeline on AWS. The infrastructure is defined using Terraform and is structured into a series of logical, independently deployable components.

## Architecture Overview

The architecture is a fully decoupled, event-driven pipeline designed for resilience, security, and operational excellence. The high-level data flow is as follows:

1.  An external party uploads raw data files to a secure **S3 Landing Bucket**.
2.  The S3 `ObjectCreated` event triggers a message to an **SQS Queue**, which decouples ingestion from processing.
3.  An **AWS Lambda Function** polls the queue in batches, processes the files, and performs several key actions:
    *   It aggregates multiple raw files into a single, compressed Gzip bundle.
    *   It calculates a SHA-256 hash of the bundle for data integrity validation.
    *   It archives the final bundle to a long-term **S3 Archive Bucket**.
    *   It securely delivers the bundle to an on-premise NiFi endpoint via HTTPS.
4.  **CloudWatch** provides comprehensive monitoring, logging, and a sophisticated alerting strategy.
5.  All stateful resources are encrypted using a **Customer-Managed KMS Key**.

## Terraform Project Structure

The codebase is organized into logical directories with clear responsibilities:

| Directory               | Purpose                                                                                                                                               |
|-------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`components/`**       | Contains the core Terraform code, broken down into four distinct infrastructure components that are deployed sequentially.                            |
| **`environments/`**     | Contains the configuration (`.tfvars`) for each deployment environment (e.g., `dev`, `prod`). This is where you define environment-specific settings. |
| **`modules/`**          | Contains reusable, generic Terraform modules. Currently, it holds the `mock_nifi_endpoint` for testing in the `dev` environment.                      |
| **`create_backend.sh`** | A one-time script to bootstrap the S3 bucket needed for Terraform's state backend.                                                                    |
| **`setup.sh`**          | The primary orchestration script used to deploy the entire infrastructure for a given environment in the correct order.                               |
| **`destroy.sh`**        | An orchestration script to destroy all infrastructure in an environment, useful for cleaning up non-production environments.                          |

## Prerequisites

*   **Terraform CLI** (`~> 1.6`)
*   **AWS CLI** (`v2+`) configured with credentials for the target AWS account.

## Deployment & Operations Workflow

### Stage 1: One-Time Backend Bootstrap (Run Once Per AWS Account)

Terraform requires an S3 bucket to store its state. This script uses the AWS CLI to create and secure this bucket before Terraform runs for the first time.

1.  Navigate to the infrastructure directory: `cd infra`
2.  Make the script executable: `chmod +x create_backend.sh`
3.  Run the bootstrap script: `./create_backend.sh`

### Stage 2: Deploying the Application Infrastructure

Use the `setup.sh` script to deploy or update the application components. This is the command you will use for all subsequent deployments.

1.  Navigate to the infrastructure directory: `cd infra`
2.  Make the script executable: `chmod +x setup.sh`
3.  Run the full deployment: `./setup.sh dev`

### Stage 3: Critical Post-Deployment Step (After First Deploy)

After the `setup.sh` script completes successfully for the first time, you **must** manually populate the value for the NiFi credentials secret. The application will not function until this step is completed.

Run the following AWS CLI command:
```bash
aws secretsmanager put-secret-value \
  --secret-id "data-aggregator/nifi-credentials-dev" \
  --secret-string '{"username":"dev-user","password":"a-secure-password-goes-here"}' \
  --region eu-west-2
```

### Stage 4: Destroying the Infrastructure (Non-Production Only)

To completely remove all infrastructure from a non-production environment, use the `destroy.sh` script.

> [!WARNING]
> This action is irreversible and will permanently delete all created resources, including S3 buckets and their contents (if `prevent_destroy` is disabled). Only use this in non-production environments.

1.  Make the script executable: `chmod +x destroy.sh`
2.  Run the destruction script for the `dev` environment: `./destroy.sh dev`

---

This concludes the entire infrastructure definition and orchestration part of our project. You now have a complete, approved, and fully documented IaC codebase.

It's time to build the final piece: **the Python Lambda function.**
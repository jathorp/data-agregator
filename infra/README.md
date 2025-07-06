# Real-Time Data Aggregation Pipeline

This repository contains the complete Infrastructure as Code (IaC) for a real-time data ingestion and aggregation pipeline on AWS. The infrastructure is defined using Terraform and is structured into a series of logical, independently managed components.

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
5.  All stateful resources are encrypted and secured following the principle of least privilege.

## Terraform Project Structure

The codebase is organized into logical directories with clear responsibilities. The old top-down orchestration scripts (`setup.sh`, `destroy.sh`) have been **removed** in favor of a more flexible, component-centric approach.

| Directory               | Purpose                                                                                                                                               |
|-------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`components/`**       | Contains the core Terraform code, broken down into distinct infrastructure components. Each component is managed as a standalone unit.                |
| **`components/tf.sh`**  | **(New)** Standardized wrapper script inside each component. **This is the primary tool for all deployment, planning, and state operations.**         |
| **`environments/`**     | Contains the configuration (`.tfvars`) for each deployment environment (e.g., `dev`, `prod`). This is where you define environment-specific settings. |
| **`modules/`**          | Contains reusable, generic Terraform modules. For example, the `mock_nifi_endpoint` for testing in the `dev` environment.                             |
| **`scripts/`**          | **(New)** Contains helper and maintenance scripts. The `tf.sh.template` (the master copy of the wrapper) and the `sync-wrappers.sh` script live here. |
| **`one_time_setup.sh`** | A script to bootstrap the S3 backend and other prerequisites. This only needs to be run once per AWS account.                                         |

## Prerequisites

*   **Terraform CLI** (`~> 1.6`)
*   **AWS CLI** (`v2+`) configured with credentials for the target AWS account.

---

## How to Work with This Repository

### Stage 1: One-Time Backend Bootstrap (Run Once Per AWS Account)

Terraform requires an S3 bucket to store its state. This script uses the AWS CLI to create and secure this bucket before Terraform is run for the first time.

1.  Navigate to the infrastructure directory: `cd infra`
2.  Run the bootstrap script: `./one_time_setup.sh`

### Stage 2: The Core Workflow - Managing Components

All day-to-day operations are now performed from within the specific component directory you are working on, using the `tf.sh` wrapper.

**The standard process:**
1.  Navigate to the component directory you wish to change.
2.  Run the `tf.sh` wrapper with the target environment and the Terraform command.

```sh
# Example: To plan a change for the network in the 'dev' environment
cd components/01-network/
./tf.sh dev plan

# Example: To apply the change
./tf.sh dev apply
```

#### Component Deployment Order

For a brand-new environment, you must deploy the components in sequence. To destroy an environment, you **MUST** destroy them in the **reverse order**.

*   **Deployment Order:** `00-security` -> `01-network` -> `02-stateful-resources` -> `03-application` -> `04-observability`
*   **Destruction Order:** `04-observability` -> `03-application` -> `02-stateful-resources` -> `01-network` -> `00-security`

### Stage 3: Critical Post-Deployment Step (After First Deploy)

After the `03-application` component is deployed successfully for the first time, you **must** manually populate the NiFi credentials in AWS Secrets Manager. The application will not function until this is done.

Run the following AWS CLI command (replacing values as needed for the environment):
```bash
aws secretsmanager put-secret-value \
  --secret-id "data-aggregator/nifi-credentials-dev" \
  --secret-string '{"username":"dev-user","password":"a-secure-password-goes-here"}' \
  --region eu-west-2
```

---

## Specialized Workflows

### Updating the Lambda Function Code

> [!IMPORTANT]
> The deployment of the Lambda function's application code is now **decoupled** from the infrastructure. You no longer need to run a slow `terraform apply` just to update Python code. This allows for much faster development cycles.

**(Coming Soon)** A dedicated `deploy-lambda.sh` script will be provided for this purpose. It will package the code, upload it to S3, and update the Lambda function directly, all in a few seconds.

### Updating the `tf.sh` Wrapper Script

The `tf.sh` script is the same across all components. To ensure consistency, it is managed from a central template. **DO NOT edit the `tf.sh` files in the component directories directly.**

To make a change to the wrapper:

1.  **Edit the Template:** Open and modify the master template file:
    *   `infra/scripts/tf.sh.template`

2.  **Run the Sync Script:** From the `infra/` directory, run the synchronization script. This copies the updated template to all component directories.
    ```sh
    ./scripts/sync-wrappers.sh
    ```

3.  **Commit the Changes:** Add the template file and all the updated `tf.sh` files to your Git commit.
````
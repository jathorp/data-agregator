# Component: 01-Network

This Terraform component is responsible for provisioning the foundational network infrastructure for the Data Aggregation Pipeline project. It creates a secure, highly available, and resilient Virtual Private Cloud (VPC) that serves as the basis for all other components.

## Key Features & Design Decisions

This network is built to a production-grade standard, incorporating several key design decisions based on the AWS Well-Architected Framework.

### 1. High Availability (Multi-AZ)

*   **What:** The VPC and its subnets are deployed across multiple Availability Zones (AZs).
*   **Why:** This design eliminates single points of failure at the AZ level, ensuring that an outage in one data center does not take down the entire application. This is a core requirement for meeting the project's availability goals (NFR-01).

### 2. Public & Private Subnet Tiers

*   **What:** The architecture is segregated into two distinct subnet tiers:
    *   **Public Subnets:** Have a direct route to the internet via an Internet Gateway. They are used for resources that need to be publicly accessible (like NAT Gateways or load balancers).
    *   **Private Subnets:** Have no direct route to the internet. Resources in these subnets (like the application Lambda) can only reach the internet via a NAT Gateway.
*   **Why:** This is a fundamental security best practice. It protects application resources from direct inbound traffic from the internet, reducing the attack surface.

### 3. Highly Available NAT Gateways

*   **What:** A separate NAT Gateway is provisioned in each Availability Zone's public subnet. Private subnets are configured to route outbound traffic through the NAT Gateway in their *own* AZ.
*   **Why:** This prevents the NAT Gateway from being a single point of failure. If one AZ's NAT Gateway fails, resources in other AZs remain unaffected.

### 4. Secure & Optimized Connectivity with VPC Endpoints

*   **What:** VPC Endpoints are provisioned for all AWS services the application communicates with (S3, DynamoDB, SQS, KMS, Secrets Manager).
*   **Why:** This provides three major benefits:
    *   **Security:** Traffic between the VPC and these AWS services never leaves the AWS private network, completely bypassing the public internet.
    *   **Reliability:** Provides a more stable, lower-latency connection compared to traversing the internet.
    *   **Cost:** Traffic to Gateway Endpoints (S3, DynamoDB) is free. Traffic to Interface Endpoints avoids NAT Gateway data processing charges.

### 5. Robust Map-Based Configuration

*   **What:** The configuration for subnets is defined using maps keyed by the Availability Zone name (`"eu-west-2a" = "10.0.1.0/24"`).
*   **Why:** This makes the relationship between an AZ and its CIDR block explicit and declarative. It is less error-prone and easier to read and maintain than relying on the order of elements in parallel lists.

## Input Variables

| Name                   | Description                                                     | Type          | Required |
|------------------------|-----------------------------------------------------------------|---------------|:--------:|
| `project_name`         | The name of the project.                                        | `string`      |   Yes    |
| `environment_name`     | The name of the environment (e.g., dev, prod).                  | `string`      |   Yes    |
| `vpc_cidr_block`       | The CIDR block for the VPC.                                     | `string`      |   Yes    |
| `private_subnet_cidrs` | A map of CIDR blocks for the private subnets, keyed by AZ name. | `map(string)` |   Yes    |
| `public_subnet_cidrs`  | A map of CIDR blocks for the public subnets, keyed by AZ name.  | `map(string)` |   Yes    |

## Outputs

| Name                 | Description                                              |
|----------------------|----------------------------------------------------------|
| `vpc_id`             | The ID of the main VPC.                                  |
| `private_subnet_ids` | A map of private subnet IDs, keyed by Availability Zone. |
| `public_subnet_ids`  | A map of public subnet IDs, keyed by Availability Zone.  |

## Deployment Instructions

Follow these steps to deploy or update the network infrastructure.

### Prerequisites

*   Terraform CLI (`~> 1.6`) is installed.
*   AWS CLI is installed and configured with credentials that have permission to create the required network resources.

### Step 1: Navigate to the Component Directory

Open your terminal and change into this component's directory.

```bash
cd components/01-network
```

### Step 2: Initialize Terraform

Run `terraform init` to initialize the backend and download the required providers. You must provide the configuration for the S3 backend where the Terraform state file will be stored.

> [!NOTE]
> The `-backend-config` values must point to the S3 bucket where you store your Terraform state and the key where this *specific component's* state should live.

```bash
terraform init -backend-config="../../environments/dev/backend.tfvars"
```

*Your `environments/dev/backend.tfvars` file should look something like this:*
```hcl
# environments/dev/backend.tfvars
bucket = "your-terraform-state-bucket-name"
key    = "dev/components/01-network.tfstate"
region = "eu-west-2"
```

### Step 3: Plan and Apply Changes

Run `terraform plan` to see a preview of the resources that will be created. You must provide the variables file for your target environment.

> [!NOTE]
> The `-var-file` must point to the `.tfvars` file that contains the input variables for this component.

```bash
terraform plan -var-file="../../environments/dev/network.tfvars"
```

If the plan is acceptable, apply the changes.

```bash
terraform apply -var-file="../../environments/dev/network.tfvars"
```

Terraform will prompt for confirmation before proceeding. Type `yes` to create the infrastructure.
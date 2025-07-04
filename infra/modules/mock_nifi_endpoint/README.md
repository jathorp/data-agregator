# Module: Mock NiFi Endpoint

This Terraform module creates a simple, serverless, and secure test harness that acts as a stand-in for the on-premise NiFi endpoint. It is intended for use in non-production environments (like `dev`) to allow for end-to-end pipeline testing without requiring a real network connection to an on-premise system.

## Key Features & Design Decisions

### 1. Serverless Endpoint (ALB Fixed-Response)

*   **What:** The core of the module is an internal Application Load Balancer (ALB) with a listener configured for a **fixed-response**. It does not forward traffic to any backend compute (like EC2 or containers). It simply accepts the HTTPS request and returns a `200 OK` status code.
*   **Why:** This is an extremely cost-effective and low-maintenance way to create a realistic HTTP endpoint. It perfectly simulates a successful delivery to NiFi, allowing us to test the Lambda function's delivery logic, IAM permissions, and network configuration.

### 2. Secure by Default

*   **What:**
    *   The ALB is **internal**, meaning it is only accessible from within the VPC and has no public IP address.
    *   It is placed in **private subnets** for maximum network segmentation.
    *   Access logs are sent to a dedicated S3 bucket. The bucket policy is hardened to only allow the official AWS ELB service principal to write logs, following the principle of least privilege.
*   **Why:** This ensures the test harness itself does not create a new security risk or attack surface.

## Input Variables

| Name                 | Description                                                  | Type         | Required |
| -------------------- | ------------------------------------------------------------ | ------------ | :------: |
| `project_name`       | The name of the project.                                     | `string`     |   Yes    |
| `environment_name`   | The name of the environment (e.g., dev).                     | `string`     |   Yes    |
| `vpc_id`             | ID of the VPC where the endpoint will be created.            | `string`     |   Yes    |
| `private_subnet_ids` | A list of private subnet IDs to place the internal ALB in.   | `list(string)` |   Yes    |

## Outputs

| Name                         | Description                                            |
| ---------------------------- | ------------------------------------------------------ |
| `endpoint_dns_name`          | The internal DNS name of the mock endpoint's ALB.      |
| `endpoint_security_group_id` | The Security Group ID of the mock endpoint's ALB.      |

## Usage Example

This module is called from the `03-application` component. The `count` meta-argument ensures it is only created when `var.environment_name` is "dev".

```terraform
# In components/03-application/main.tf

module "mock_nifi_endpoint" {
  source = "../../modules/mock_nifi_endpoint"

  count = var.environment_name == "dev" ? 1 : 0

  project_name       = var.project_name
  environment_name   = var.environment_name
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  private_subnet_ids = values(data.terraform_remote_state.network.outputs.private_subnet_ids)
}
```


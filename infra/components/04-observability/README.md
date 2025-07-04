# Component: 04-Observability

This Terraform component provisions the monitoring, alarming, and notification infrastructure for the Data Aggregation Pipeline. Its primary goal is to provide deep visibility into the health of the pipeline, enabling proactive issue detection and rapid response to failures, as required by the project's observability requirements (NFR-07).

## Key Features & Design Decisions

This component implements a sophisticated, multi-layered monitoring strategy designed to provide high-fidelity signals while reducing alert fatigue.

### 1. Two-Tiered Alerting (Warning vs. Critical)

*   **What:** Two separate SNS topics (`alerts_warning` and `alerts_critical`) are created. Alarms are routed to the appropriate topic based on severity.
*   **Why:** This allows operations teams to route alerts to different destinations. For example, `CRITICAL` alerts might trigger a PagerDuty incident, while `WARNING` alerts might post a notification to a Slack channel. This separation is key to preventing alert fatigue.

### 2. High-Confidence Outage Detection (Composite Alarm)

*   **What:** A `Composite Alarm` is configured to fire only when *multiple* failure conditions are met simultaneously (e.g., the SQS queue is aging *and* the Lambda is throwing errors).
*   **Why:** A single metric (like a few Lambda errors) might not indicate a true outage. By combining signals, this alarm provides a very high-confidence notification that the entire pipeline is down, justifying an immediate, high-priority response.

### 3. Proactive "Denial-of-Wallet" Protection (Anomaly Detection)

*   **What:** An `Anomaly Detection` alarm monitors the number of incoming messages to the SQS queue. It doesn't use a fixed threshold but instead learns the normal traffic pattern and alerts on significant deviations.
*   **Why:** This is a proactive defense against misconfigured upstream clients or abuse that could cause a massive, unexpected spike in costs. It provides an early warning before costs escalate significantly.

### 4. Foundational Metric Alarms

*   **What:** The component includes standard, critical alarms on key metrics:
    *   `ApproximateNumberOfMessagesVisible` in the **Dead-Letter Queue (DLQ)**.
    *   `ApproximateAgeOfOldestMessage` in the main processing queue.
    *   `Errors` count for the application Lambda function.
*   **Why:** These are the fundamental health indicators of the pipeline. Any breach of these alarms points to a specific, actionable problem (poison-pill messages, processing backlog, or application code failure).

## Input Variables

| Name               | Description                                    | Type     | Required |
|--------------------|------------------------------------------------|----------|:--------:|
| `project_name`     | The name of the project.                       | `string` |   Yes    |
| `environment_name` | The name of the environment (e.g., dev, prod). | `string` |   Yes    |

## Outputs

| Name                            | Description                                         |
|---------------------------------|-----------------------------------------------------|
| `alerts_warning_sns_topic_arn`  | The ARN of the SNS topic for WARNING level alerts.  |
| `alerts_critical_sns_topic_arn` | The ARN of the SNS topic for CRITICAL level alerts. |

## Deployment Instructions

### Prerequisites

*   Terraform CLI (`~> 1.6`) is installed.
*   AWS CLI is installed and configured.
*   The `01-network`, `02-stateful-resources`, and `03-application` components must be successfully deployed first.

### Deployment Steps

> [!NOTE]
> This is the final component in the deployment chain.

1.  **Navigate to Directory:** `cd components/04-observability`
2.  **Initialize Terraform:**
    ```bash
    terraform init -backend-config="../../environments/dev/backend.tfvars"
    ```
3.  **Plan and Apply Changes:**
    ```bash
    terraform plan -var-file="../../environments/dev/observability.tfvars"
    terraform apply -var-file="../../environments/dev/observability.tfvars"
    ```

---
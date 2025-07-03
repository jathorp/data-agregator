### **Project: Real-Time Data Ingestion and Aggregation Pipeline**

**Document Version: 6.1**
**Date:** July 5, 2025
**Author(s):** john51246

#### **1. Executive Summary**

This document outlines the requirements and technical design for a new data pipeline. The primary goal is to reliably ingest a high volume of small data files from an external third party, process them in near real-time, and securely deliver aggregated, compressed data batches to an on-premise Apache NiFi instance. The design prioritizes resilience, security, and operational excellence.

The projected data volume is ~864,000 objects per day (avg. 10 files/sec). The solution leverages a modern, serverless, event-driven architecture on AWS. Key features include a configurable Circuit Breaker pattern for robust fault tolerance against downstream failures, end-to-end data integrity validation using cryptographic hashes, and a comprehensive testing strategy to ensure reliability under load. The entire infrastructure will be defined as code (IaC) using Terraform for automated and auditable management.

**Primary Success Metric:** ≥ 99.9% of incoming files will be successfully processed and delivered to the on-premise NiFi endpoint within 3 minutes of their arrival in the S3 landing zone under normal operating conditions.

#### **2. Business & Functional Requirements**
*(No changes in this section)*

| ID     | Requirement      | Details                                                                                                                                                                      |
|:-------|:-----------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| REQ-01 | Data Ingestion   | The system must provide a secure S3 bucket as a landing zone for an external party to upload data files.                                                                     |
| REQ-02 | Data Aggregation | The system must collect incoming data files and process them in near real-time batches. An archive is created from all unique files processed in a single Lambda invocation. |
| REQ-03 | Data Compression | The aggregated data batch must be compressed (Gzip) to reduce its size for efficient storage and transfer.                                                                   |
| REQ-04 | Secure Delivery  | The final compressed data batch must be securely delivered to the on-premise NiFi ingest endpoint via an HTTP POST request.                                                  |

#### **3. Non-Functional Requirements**

| ID     | Category                     | Requirement & Rationale                                                                                                                                                                                                                                                                                                                                                                           |
|:-------|:-----------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| NFR-01 | Availability                 | The ingestion endpoint (S3) must achieve ≥ 99.99% availability. The end-to-end pipeline should be resilient to transient failures of individual components.                                                                                                                                                                                                                                       |
| NFR-02 | Latency (SLO)                | 95% of files should be delivered to the on-premise endpoint within 2 minutes of arrival. 99.9% should be delivered within 3 minutes.                                                                                                                                                                                                                                                              |
| NFR-03 | Durability / Retention       | Raw files in the S3 landing zone will be retained for 7 days for immediate audit/replay. After 7 days, they will be transitioned to S3 Glacier Deep Archive. **This retention strategy is accepted. The business acknowledges the 9-12 hour restore time for Deep Archive is acceptable for archival purposes.**                                                                                  |
| NFR-04 | Resilience & Backlog         | In the event of an outage of the on-premise endpoint, the system must buffer incoming data without loss. The SQS queue will be configured with a 4-day message retention period. **The 4-day backlog capacity is approved for business continuity.** Alerts will trigger if the backlog exceeds 1 hour's worth of data. An operational runbook will define the response procedure for this alert. |
| NFR-05 | Scalability                  | The system must handle the baseline load of 10 files/sec and be able to automatically scale to handle bursts of up to 100 files/sec without performance degradation. **Note:** Default Lambda concurrency limits will be monitored during load testing to ensure they are not a bottleneck.                                                                                                       |
| NFR-06 | Security                     | Communication must be encrypted-in-transit (TLS 1.2+) at all stages. Data must be encrypted-at-rest in S3 and SQS. Access credentials for the NiFi endpoint will be managed by AWS Secrets Manager with a defined rotation policy. IAM roles will adhere to the principle of least privilege.                                                                                                     |
| NFR-07 | Observability                | The system must provide key health metrics, including queue depth, processing errors, and processing latency. Critical failures (e.g., failed batches, connectivity loss) must trigger automated alerts.                                                                                                                                                                                          |
| NFR-08 | Resilience / Fault Tolerance | The system must gracefully handle prolonged outages of the on-premise NiFi endpoint. It must detect when the endpoint is unavailable and "fail-fast" to prevent excessive retries, cost, and load on the failing system. It must automatically resume processing once the endpoint becomes available again.                                                                                       |
| NFR-09 | Data Integrity               | End-to-end data integrity must be guaranteed. The system will compute a cryptographic hash of the data payload before delivery. The receiving endpoint must validate this hash to protect against data corruption during transit.                                                                                                                                                                 |
| NFR-10 | Network Security             | Connectivity between AWS and the on-premise data center must be established over a secure, private channel. The solution will be either an AWS Site-to-Site VPN or AWS Direct Connect, not the public internet.                                                                                                                                                                                   |

#### **4. Proposed Architecture (v6.1 - As-Built Design)**

##### **4.1. High-Level Design**

The architecture is a fully decoupled, event-driven pipeline. The design uses a direct SQS Event Source Mapping for the Lambda function, allowing for automatic scaling based on queue depth and robust buffering.

To enhance resilience and security, the design incorporates:
*   **Idempotency Management:** A DynamoDB table with a 7-day TTL tracks processed file keys to prevent duplicates, enforcing a "first-in wins" policy.
*   **Circuit Breaker:** A second DynamoDB table implements a configurable circuit breaker to gracefully handle downstream NiFi endpoint failures.
*   **Data Integrity:** A SHA-256 hash of the payload is sent as an HTTP header with every request.
*   **Partial Batch Failure Handling:** The Lambda is designed to process messages individually within a batch, ensuring a single bad message does not halt processing for the entire batch.

##### **4.2. Architectural Diagram**

The diagram below illustrates the sequential flow of data and actions within the pipeline.

```mermaid
flowchart TD
    %% ───────── External Entities ─────────
    ExternalParty["External Party"]
    subgraph "On-Premise Data Center"
        NiFi["fa:fa-network-wired<br/>NiFi HTTP Endpoint"]
    end

    %% ───────── AWS Cloud (eu-west-2) System Boundary ─────────
    subgraph "AWS Cloud (eu-west-2)"
        %% Main Data Flow Nodes
        S3["fa:fa-database<br/>S3 Bucket"]
        SQS["fa:fa-list-alt<br/>SQS Queue"]
        Lambda["fa:fa-microchip<br/>Aggregator Lambda"]
        SecureTunnel["fa:fa-shield-alt<br/>VPN / Direct Connect"]
        DLQ["fa:fa-exclamation-triangle<br/>Dead-Letter Queue"]
        
        %% Supporting Service Nodes
        DynamoCB["fa:fa-bolt<br/>Circuit Breaker Table"]
        DynamoDB["fa:fa-table<br/>Idempotency Table<br/>(7-Day TTL)"]
        SecretsManager["fa:fa-key<br/>Secrets Manager"]
        CloudWatch["fa:fa-chart-bar<br/>CloudWatch Metrics & Alarms"]
        
        %% Lambda Processing Logic Sub-graph
        subgraph "Lambda Processing Logic"
            direction LR
            L_Start("Start")
            L_CheckCircuit["4 - Check Circuit State"]
            L_ProcessBatch["5 - Process Batch<br/>(Check Idempotency, Download)"]
            L_GetCreds["6 - Get Credentials"]
            L_Post["7 - POST Gzip Archive"]
            L_UpdateCircuit["8 - Update Circuit State"]
            L_Metrics["9 - Push Metrics"]
            L_End("End")
    
            L_Start --> L_CheckCircuit --> L_ProcessBatch --> L_GetCreds --> L_Post --> L_UpdateCircuit --> L_Metrics --> L_End
        end

        %% Internal System Connections
        S3              -->|2 - Event Notification| SQS
        SQS             -->|3 - Triggers Lambda with batch<br/>(Batch Size: 100, Window: 10s)| Lambda
        Lambda -- "Reads State" --> DynamoCB
        Lambda -- "Checks & Updates Keys" --> DynamoDB
        SecretsManager -- "Provides Credentials" --> Lambda
        Lambda -- "Pushes Logs & Metrics" --> CloudWatch
        Lambda --> SecureTunnel
        SQS -->|10 - Persistent Failure<br/>(Partial Batch Aware)| DLQ
    end

    %% ───────── Boundary Crossing Connections ─────────
    ExternalParty   -->|1 - Uploads files (HTTPS)<br/>(Scoped IAM/IP Policy)| S3
    SecureTunnel -->|"(X-Content-SHA256 Header)"| NiFi
    NiFi -- "HTTP Response<br/>(Success/Failure)" --> Lambda

    %% ───────── Styling ─────────
    linkStyle 18,19,20 stroke-width:2px,fill:none,stroke:black;
    classDef main fill:#FF9900,stroke:#333,stroke-width:2px;
    classDef supp fill:#4DA4DB,stroke:#333,stroke-width:2px;
    classDef conn fill:#0073BB,stroke:#333,stroke-width:2px;
    classDef danger fill:#CC0000,stroke:#333,stroke-width:2px;
    classDef key fill:#D6EAF8,stroke:#333,stroke-width:2px;

    class Lambda,S3 main
    class SQS main,fill:#FF4F8B
    class DynamoDB,DynamoCB,SecretsManager,CloudWatch supp
    class SecureTunnel,NiFi conn
    class DLQ danger
    class ExternalParty key
```

##### **4.3. Design Considerations & Risk Mitigation**

*   **Idempotency & State Management:** The Lambda uses a DynamoDB table to track processed S3 object keys. **The business requirement is "first-in wins"; subsequent uploads of a file with the same name within the 7-day TTL window will be identified and correctly skipped.**
*   **Downstream Fault Tolerance (Circuit Breaker):** The circuit breaker logic is implemented to prevent cascading failures. The state (CLOSED, OPEN, HALF-OPEN) is stored in DynamoDB.
    *   **Logic:**
        *   **CLOSED to OPEN:** The circuit trips to `OPEN` after a configured number of consecutive delivery failures.
        *   **OPEN to HALF-OPEN:** After a configured reset period, the circuit moves to `HALF-OPEN`.
        *   **HALF-OPEN:** The system attempts a single "canary" batch delivery. Success moves the circuit to `CLOSED`; failure moves it back to `OPEN`.
    *   **Configuration:** The following parameters are managed as variables in Terraform to allow for tuning without code changes:
        *   `TripThreshold`: **5** (consecutive failures)
        *   `ResetPeriod`: **60** (seconds)
*   **Error Handling & Partial Batch Failures:** To maximize throughput, the system will leverage SQS's partial batch failure reporting.
    *   **Logic:** If the Lambda function receives a batch of 100 messages, it will iterate through them individually. If a single file download fails (e.g., S3 object deleted prematurely), that specific failure will be logged. The Lambda will continue to process the other 99 messages, create a compressed archive, and deliver it.
    *   **Implementation:** The Lambda will return a `batchItemFailures` response to SQS, containing the `messageId` of only the message(s) that failed. SQS will then be responsible for redriving only the failed messages for retry, rather than the entire batch.
*   **Secure Delivery & Data Integrity:** To guarantee end-to-end integrity (NFR-09), the Lambda will compute a SHA-256 hash of the compressed Gzip archive and include it in a custom HTTP header (`X-Content-SHA256`). The NiFi flow must be configured to validate this hash.
*   **Lambda Configuration & Optimization:**
    *   **SQS Batching:** The SQS event source mapping will be configured to optimize the trade-off between latency and cost. The configuration will be managed in Terraform.
        *   `BatchSize`: **100** (process up to 100 files per invocation)
        *   `MaximumBatchingWindowInSeconds`: **10** (wait up to 10 seconds to fill a batch)
    *   **Memory/CPU:** Optimal memory will be determined during load testing via the AWS Lambda Power Tuning tool.

#### **5. Implementation & Operations Plan**

| Phase          | Activity                         | Key Deliverables / Actions                                                                                                                                                                                                                                                                                             |
|:---------------|:---------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1. Infra Setup | Core Infrastructure Provisioning | Terraform modules for all components. This includes configuring the S3 bucket policy, SQS batching parameters, Circuit Breaker thresholds, and DynamoDB TTL. The secure network connection (VPN/Direct Connect) will be established.                                                                                   |
| 2. Dev & Test  | Lambda Logic & Unit Testing      | Develop idempotent Python code for the Lambda, including SHA-256 hash generation and partial batch failure logic. A `pytest` suite will use `moto` to mock AWS services and `requests-mock` to simulate the NiFi endpoint.                                                                                             |
| 3. Integration | E2E & Fault Tolerance Testing    | Deploy to a staging environment. Conduct comprehensive testing as defined in the Testing Strategy (Section 7). This includes validating the circuit breaker functionality and the partial batch failure mechanism.                                                                                                     |
| 4. Deployment  | Production Rollout               | Use a blue/green deployment strategy for the Lambda function (via aliases and traffic shifting) to enable zero-downtime updates and instant rollbacks.                                                                                                                                                                 |
| 5. Operations  | Monitoring & Alerting            | Configure CloudWatch Alarms for: 1) SQS queue depth, 2) ApproximateAgeOfOldestMessage, 3) High Lambda error/throttle rates, 4) Messages in the DLQ, 5) Circuit Breaker state `OPEN` for >15 minutes. **A new AWS Budgets alarm will be configured to alert if forecasted monthly costs exceed the defined threshold.** |

#### **6. High-Level Cost Estimate**
This is a preliminary estimate and will be refined. Assumes `eu-west-2` region.

| Service                    | Dimension                                        | Estimated Monthly Cost      | Notes                                                                                                                                     |
|:---------------------------|:-------------------------------------------------|:----------------------------|:------------------------------------------------------------------------------------------------------------------------------------------|
| S3                         | 26M PUTs, 165 GB-Mo (Hot), 2TB-Mo (Deep Archive) | ~$145                       | Assumes 100KB/file avg, 7-day hot tier.                                                                                                   |
| SQS                        | 26M Requests                                     | ~$10                        | Standard Queue pricing.                                                                                                                   |
| Lambda                     | ~2.6M invocations, 1.2M GB-seconds               | ~$25                        | Based on ~2.6M monthly invocations (assuming SQS batch size of 10), 1024MB memory. To be optimized with Power Tuning.                     |
| DynamoDB (Idempotency)     | On-Demand Capacity, low usage w/ TTL             | ~$5                         | For idempotency tracking. TTL keeps storage costs low.                                                                                    |
| DynamoDB (Circuit Breaker) | On-Demand Capacity, very low usage               | ~$1                         | Negligible cost that prevents potentially large costs from failed Lambda invocations during an outage.                                    |
| **CloudWatch**             | **Metrics, Logs, Alarms**                        | **~$10**                    | **Standard logging and custom metrics for circuit breaker state. An AWS Budget alarm is included.**                                       |
| Network Solution           | VPN or Direct Connect                            | ~$200 - $1,000+             | This is a significant variable. A Site-to-Site VPN is on the lower end, while Direct Connect is higher. This is a fixed operational cost. |
| Data Transfer              | ~650 GB Egress over private network              | ~$30                        | Data transfer over VPN/Direct Connect is cheaper than public internet.                                                                    |
| **Total (Est.)**           |                                                  | **~$426 - $1,226+ / month** | **Highlights the significant impact of the network solution on the final monthly cost.**                                                  |

#### **7. Testing Strategy**

##### **7.1. Guiding Principles**
*   **Test for Failure:** Actively simulate and test failure scenarios, not just the happy path.
*   **Automate Everything:** All tests should be scriptable and runnable in a CI/CD pipeline.
*   **Test in Production-like Environments:** The staging environment must be a 1:1 replica of production.

##### **7.2. Unit Testing**
*   **Scope:** Testing individual Python functions in isolation.
*   **Tools:** `pytest`, `moto` (to mock AWS services), `requests-mock` (to simulate NiFi).
*   **Key Scenarios:**
    *   Successful processing of a batch of S3 event messages.
    *   Correct generation of the `X-Content-SHA256` header.
    *   Idempotency logic correctly identifying and skipping a previously processed file.
    *   **Partial Batch Failure:** Correctly identifies and returns specific `messageId`s for failed items within a batch, allowing SQS to redrive only those messages.

##### **7.3. Integration Testing**
*   **Scope:** Verifying the interactions between the deployed AWS services.
*   **Tools:** Terraform deployment to a test environment, AWS CLI/SDK scripts.
*   **Key Scenarios:**
    *   An `s3:ObjectCreated:*` event correctly creates a message in the SQS queue.
    *   The Lambda's IAM role permissions are correctly enforced (e.g., cannot write to S3).
    *   The `BatchSize` (100) and `MaximumBatchingWindowInSeconds` (10) settings are correctly applied to the SQS event source mapping.
    *   TTL configuration on the idempotency DynamoDB table correctly removes old items.
    *   Terraform variables for the circuit breaker are correctly read by the Lambda function.

##### **7.4. End-to-End (E2E) & Fault Tolerance Testing**
*   **Scope:** Testing the entire pipeline from file upload to NiFi delivery, focusing on resilience.
*   **Tools:** Staging environment, custom load generation scripts, network ACLs/firewall rules to simulate outages.
*   **Key Scenarios:**
    *   **Circuit Breaker Test:**
        *   Start a baseline load.
        *   Block network access from the Lambda's VPC to the staging NiFi endpoint.
        *   **Verify:** After **5** failed deliveries, the circuit state in DynamoDB changes to `OPEN`. The "Circuit Open" CloudWatch alarm fires.
        *   Unblock network access after **60+ seconds**.
        *   **Verify:** The circuit moves to `HALF-OPEN`, a canary request succeeds, the state changes back to `CLOSED`, and the SQS queue backlog is processed automatically.
    *   **Partial Batch Failure Test:**
        *   **Setup:** Push 10 valid S3 object creation events to the SQS queue. Add one event that references a non-existent S3 object key.
        *   **Verify:** The Lambda function executes, successfully POSTs a Gzip archive containing 10 files to NiFi, and logs the single failure. Verify that exactly one message is returned to the queue and is eventually moved to the Dead-Letter Queue after its configured number of retries.
    *   **DLQ Test:** Inject a completely malformed (e.g., non-JSON) message into the SQS queue and verify it is moved to the DLQ immediately without a successful Lambda invocation.

##### **7.5. Load & Performance Testing**
*   **Scope:** Validating the system meets scalability (NFR-05) and latency (NFR-02) requirements.
*   **Tools:** Load testing framework (e.g., Locust, Artillery), AWS Lambda Power Tuning tool.
*   **Key Scenarios:**
    *   **Baseline Load:** Run a sustained test at 10 files/sec and measure end-to-end latency against the 3-minute SLO.
    *   **Burst Load:** Simulate a spike to 100 files/sec and verify the system scales automatically without errors and that latency remains within acceptable bounds.
    *   **Soak Test:** Run the baseline load for an extended period (e.g., 8+ hours) to check for memory leaks or performance degradation.
    *   **Cost Optimization:** Run the Lambda Power Tuning state machine under a realistic load profile to determine the most cost-effective memory configuration.
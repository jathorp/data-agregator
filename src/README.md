# Data Aggregator Lambda

This AWS Lambda function is a core component of the real-time data ingestion pipeline. It is triggered by SQS messages originating from S3 object creation events and its primary purpose is to create secure, compressed data bundles.

## Project Overview

The function's primary responsibilities are to:

1.  **Consume** S3 object creation events from an SQS queue in batches using the **AWS Powertools for Python BatchProcessor**.
2.  **Ensure Exactly-Once Processing** by using the **AWS Powertools for Python `@idempotent` decorator**, which filters duplicate events using a DynamoDB table.
3.  **Aggregate** the content of multiple source files into a single, compressed Gzip bundle.
4.  **Stage the Bundle:** Upload the final bundle to a dedicated **S3 Distribution Bucket** using a time-partitioned key (`YYYY/MM/DD/HH/`) for efficient querying and a unique suffix to prevent key collisions.
5.  **Enable Asynchronous Archival:** The Distribution Bucket is configured with **S3 Same-Region Replication (SRR)**. This AWS-managed feature automatically copies the bundle to a long-term **Archive Bucket**, providing a resilient and decoupled mechanism for creating the authoritative, immutable record.

This single-write-plus-replication pattern is more resilient than a dual-write in code, as it cannot create orphan archive files if the Lambda crashes or times out after the first write.

## 🗂️ File Structure

The function is intentionally split into modules to enforce a clear separation of concerns, which is critical for testability and maintainability.

*   `app.py`: **The Lambda Adapter & Orchestrator**. This is the main entry point for the AWS Lambda service. It is responsible for parsing the event, initializing the Powertools utilities (Logger, Tracer, Idempotency), and orchestrating the calls between the other modules.
*   `core.py`: **The Pure Business Logic**. This module contains the core algorithm for creating the Gzip bundle. It has no knowledge of AWS, Lambda, or Powertools. It's pure, portable Python, making it easy to unit-test in isolation.
*   `clients.py`: **The I/O / Integration Layer**. This module contains wrappers for all external AWS services (S3). It isolates the business logic from the implementation details of `boto3`, making it easy to mock for tests.
*   `exceptions.py`: **Custom Exception Definitions**. Centralizes custom exceptions to provide clear, catchable error types for the application logic.
*   `schemas.py`: **Data Contracts / TypedDicts**. Provides `TypedDict` schemas for parsing incoming event data (e.g., S3 event records), enabling static analysis and improving code clarity.

## 🏛️ Design Philosophy & Key Patterns

The structure of `app.py` was carefully chosen to maximize testability, robustness, and maintainability.

### 1\. Decorator-Driven Cross-Cutting Concerns

We leverage **AWS Lambda Powertools** decorators (`@logger`, `@tracer`, `@idempotent`) to handle non-functional requirements. This cleanly separates business logic from boilerplate concerns like logging, distributed tracing, and idempotency, making the code more declarative and easier to read.

### 2\. Idempotency Key Strategy

The idempotency logic is applied to each S3 object key within an SQS message. The idempotency token is generated from the **S3 object key** (`s3.object.key`), ensuring that the aggregation logic for a specific source file is only ever executed once, even if the SQS message is delivered multiple times.

### 3\. Partitioned S3 Keys for Analytics

Bundles are written to S3 using a date-based prefix and a random suffix (e.g., `2025/07/19/09/bundle-request-id-a1b2c3d4.gz`). This partitioning is a best practice that enables efficient, cost-effective querying with services like Amazon Athena.

### 4\. Statelessness & Per-Invocation Dependencies

Dependencies (like the S3 client) are instantiated inside the `handler` function, not at the global module level. This is a critical design choice for robustness in AWS Lambda, ensuring each invocation is stateless and isolated from any leftover state from a previous "warm" execution.

### 5\. Memory-Efficient Streaming

The `core.py` module uses `SpooledTemporaryFile` and streams data directly from S3 into the Gzip compression stream. This approach is highly memory-efficient, as the Lambda never needs to load entire source files into memory, keeping costs low.

### 6\. Static Analysis with Strict Type Hinting

We use comprehensive type hints (`TypedDict`, `boto3-stubs`) and can enforce them with `mypy --strict`. This makes the code self-documenting and allows static analysis tools to catch a whole class of potential bugs before deployment.

## 🧪 Development & Testing

This project uses `pytest` and follows a **three-tiered testing strategy** to ensure correctness and confidence in our Powertools-enhanced logic.

1.  **Unit Test Business Logic**: The core business logic is tested in complete isolation by disabling the Powertools decorators.
2.  **Unit Test Decorator Behavior**: The specific configuration of the `@idempotent` decorator is tested by stubbing `boto3` calls to simulate initial, duplicate, and concurrent invocations.
3.  **Integration Smoke Testing**: A small suite of tests runs against live (or local) AWS resources to catch configuration, permission, and serialization errors.

For a complete guide with code examples for each testing tier, please see the **`README.md`** file in the tests directory.

## 🔭 Observability & Monitoring

The function is instrumented with `aws-lambda-powertools`. The following are critical alarms to configure:

*   **SQS Queue Depth:** An alarm on `ApproximateAgeOfOldestMessage` for the main SQS queue.
*   **DLQ Messages:** An alarm on `NumberOfMessagesVisible` for the Dead-Letter Queue.
*   **Distribution Bucket Size/Age:** An alarm on `NumberOfObjects` for the S3 Distribution Bucket if the downstream consumer is expected to clear it regularly.
*   **S3 Replication Latency:** An alarm on `ReplicationLatency` for the Distribution Bucket is **critical** to ensure the archival process is healthy.
*   **Lambda Errors & Traces:** Standard alarms on the `Errors` and `Throttles` metrics. Review traces in **AWS X-Ray** to debug performance issues.

## ⚙️ Environment Variables

The function requires the following environment variables to be set:

| Variable                   | Required/Default | Description                                                                                              | Example Value                              |
|:---------------------------|:-----------------|:---------------------------------------------------------------------------------------------------------|:-------------------------------------------|
| `DISTRIBUTION_BUCKET_NAME` | **Required**     | The name of the S3 bucket where bundles are staged for the consumer.                                     | `data-aggregator-prod-distribution-bucket` |
| `MAX_BUNDLE_INPUT_MB`      | Default: `100`   | The maximum cumulative size of source files allowed in a single bundle.                                  | `200`                                      |
| `SERVICE_NAME`             | **Required**     | The service name, used for structured logging and X-Ray traces.                                          | `data-aggregator`                          |
| `IDEMPOTENCY_TABLE_NAME`   | **Required**     | The name of the DynamoDB table used by the Powertools idempotency utility.                               | `data-aggregator-prod-idempotency-table`   |
| `IDEMPOTENCY_TTL_DAYS`     | **Required**     | **In days.** Retention period for idempotency records. The code converts this to seconds for Powertools. | `7`                                        |
| `LOG_LEVEL`                | **Required**     | The log level for Powertools Logger. Set to `DEBUG` for verbose output.                                  | `INFO`                                     |

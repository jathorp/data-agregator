# Data Aggregator Lambda

This AWS Lambda function is a core component of the real-time data ingestion pipeline. It is triggered by SQS messages originating from S3 object creation events and its primary purpose is to create secure, compressed data bundles.

## Project Overview

The function's primary responsibilities are to:

1.  **Consume** S3 object creation events from an SQS queue in batches.
2.  **Filter** out duplicate events using a DynamoDB table for idempotency.
3.  **Aggregate** the content of multiple source files into a single, compressed Gzip bundle.
4.  **Stage the Bundle:** Upload the final bundle to a dedicated **S3 Distribution Bucket**.
5.  **Enable Asynchronous Archival:** The Distribution Bucket is configured with **S3 Same-Region Replication (SRR)**. This AWS-managed feature automatically copies the bundle to a long-term **Archive Bucket**, providing a resilient and decoupled mechanism for creating the authoritative, immutable record.

This single-write-plus-replication pattern is more resilient than a dual-write in code, as it cannot create orphan archive files if the Lambda crashes or times out after the first write.

## 🗂️ File Structure

The function is intentionally split into modules to enforce a clear separation of concerns, which is critical for testability and maintainability.

*   `app.py`: **The Orchestrator / Lambda Adapter**. This is the main entry point for the AWS Lambda service. Its job is to handle the event/context, manage dependencies, and orchestrate the calls between the other modules.
*   `core.py`: **The Pure Business Logic**. This module contains the core algorithm for creating the Gzip bundle. It has no knowledge of AWS, Lambda, or SQS. It's pure, portable Python, making it easy to unit-test.
*   `clients.py`: **The I/O / Integration Layer**. This module contains wrappers for all external AWS services (S3, DynamoDB). It isolates the rest of the application from the implementation details of `boto3`.
*   `exceptions.py`: **Custom Exception Definitions**. Centralizes custom exceptions to prevent circular import errors and provide clear, catchable error types for the application logic.
*   `schemas.py`: **Data Contracts / TypedDicts**. Provides `TypedDict` schemas for parsing incoming event data (e.g., S3 event records), enabling static analysis and improving code clarity.

## 🏛️ Design Philosophy & Key Patterns

The structure of `app.py` was carefully chosen to maximize testability, robustness, and maintainability.

### 1. Statelessness & Per-Invocation Dependencies

The `Dependencies` class is instantiated inside the `handler` function, not at the global module level.

*   **Why?** This is a critical design choice for robustness. AWS Lambda may reuse a "warm" container for multiple invocations. By creating a fresh `Dependencies` instance every time, we guarantee each invocation is stateless and isolated from the last.

### 2. Closure-Based Dependency Access

The `record_handler` is defined as an inner function inside the main `handler`. It automatically gets access to the `deps` object created in the outer scope (a "closure").

*   **Why?** This is a simple and effective pattern for providing dependencies to the per-record processing logic without needing complex dependency injection frameworks, keeping the code clean and easy to follow.

### 3. Memory-Efficient Streaming

The `core.py` module uses `SpooledTemporaryFile` and streams data directly from S3 into the Gzip compression stream.

*   **Why?** This approach is highly memory-efficient, as the Lambda never needs to load entire source files into memory. This allows us to keep the Lambda’s memory setting (and therefore cost) low while processing large batches.

### 4. Static Analysis with Strict Type Hinting

We use comprehensive type hints (`TypedDict`, `boto3-stubs`) and can enforce them with `mypy --strict` in a CI/CD pipeline.

*   **Why?** This makes the code more self-documenting and allows static analysis tools to catch a whole class of potential bugs before the code is ever deployed.

## 🧪 Development & Testing

This project uses `pytest` for unit testing. The architecture allows for extensive mocking of external services.

```bash
# Run the unit test suite
pytest
```

## 🔭 Observability & Monitoring

The function is instrumented with `aws-lambda-powertools`. The following are critical alarms to configure:

*   **SQS Queue Depth:** An alarm on `ApproximateAgeOfOldestMessage` for the main SQS queue will alert on processing backlogs.
*   **DLQ Messages:** An alarm on `NumberOfMessagesVisible` for the Dead-Letter Queue is essential for detecting persistent processing failures.
*   **Distribution Bucket Size/Age:** An alarm on `NumberOfObjects` or `AgeOfOldestObject` for the S3 Distribution Bucket will alert if the on-premise service stops consuming files.
*   **S3 Replication Latency:** An alarm on `ReplicationLatency` for the Distribution Bucket is now critical. It will alert if the replication process to the Archive Bucket is failing or delayed.
*   **Lambda Errors:** Standard alarms on the `Errors` and `Throttles` metrics for the Lambda function.

## ⚙️ Environment Variables

The function requires the following environment variables to be set:

| Variable                   | Required/Default | Description                                                             | Example Value                              |
|:---------------------------|:-----------------|:------------------------------------------------------------------------|:-------------------------------------------|
| `IDEMPOTENCY_TABLE_NAME`   | **Required**     | The name of the DynamoDB table for idempotency tracking.                | `data-aggregator-prod-idempotency-table`   |
| `DISTRIBUTION_BUCKET_NAME` | **Required**     | The name of the S3 bucket where bundles are staged for the consumer.    | `data-aggregator-prod-distribution-bucket` |
| `IDEMPOTENCY_TTL_DAYS`     | Default: `7`     | Retention period in days for idempotency keys.                          | `7`                                        |
| `DYNAMODB_TTL_ATTRIBUTE`   | Default: `ttl`   | Name of the TTL attribute in the idempotency table.                     | `ttl`                                      |
| `BUNDLE_KMS_KEY_ID`        | Optional         | The ARN or ID of the KMS key used for SSE-KMS encryption.               | `arn:aws:kms:eu-west-2:123:key/abc-123`    |
| `MAX_BUNDLE_INPUT_MB`      | Default: `100`   | The maximum cumulative size of source files for a single bundle.        | `200`                                      |
| `POWERTOOLS_LOG_LEVEL`     | Default: `INFO`  | The log level for Powertools Logger. Set to `DEBUG` for verbose output. | `INFO`                                     |
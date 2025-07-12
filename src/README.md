# Data Aggregator Lambda

This AWS Lambda function is a core component of the real-time data ingestion pipeline. It is triggered by SQS messages originating from S3 object creation events.

## Project Overview

The function's primary responsibilities are to:

1.  **Consume** S3 object creation events from an SQS queue in batches.
2.  **Filter** out duplicate events using a DynamoDB table for idempotency.
3.  **Aggregate** the content of multiple source files into a single, compressed Gzip bundle.
4.  **Perform a dual-write** of this canonical bundle to two S3 locations:
      * An **Archive Bucket** for long-term, immutable storage.
      * A **Distribution Bucket** for the on-premise service to pull from.

## 🗂️ File Structure

The function is intentionally split into three top-level modules to enforce a clear separation of concerns, which is critical for testability and maintainability.

  * `app.py`: **The Orchestrator / Lambda Adapter**. This is the main entry point for the AWS Lambda service. Its job is to handle the event/context, manage dependencies, and orchestrate the calls between the other modules.
  * `core.py`: **The Pure Business Logic**. This module contains the core algorithm for creating the Gzip bundle. It has no knowledge of AWS, Lambda, or SQS. It's pure, portable Python, making it easy to unit-test.
  * `clients.py`: **The I/O / Integration Layer**. This module contains wrappers for all external AWS services (S3, DynamoDB). It isolates the rest of the application from the implementation details of `boto3`.

## 🏛️ Design Philosophy & Key Patterns

The structure of `app.py` was carefully chosen to maximize testability, robustness, and maintainability.

### 1\. Statelessness & Per-Invocation Dependencies

The `Dependencies` class is instantiated inside the `handler` function, not at the global module level.

  * **Why?** This is a critical design choice for robustness. AWS Lambda may reuse a "warm" container for multiple invocations. By creating a fresh `Dependencies` instance every time, we guarantee each invocation is stateless and isolated.

### 2\. Explicit Dependency Injection (DI)

We use a factory function, `make_record_handler(dependencies: Dependencies)`, to supply the per-message processor with the dependencies it needs.

  * **Why?** This makes dependencies explicit. For testing, we can easily create a mock `Dependencies` object and pass it into our functions, giving us complete control over the test environment.

### 3\. Memory-Efficient Streaming

The `core.py` module uses `SpooledTemporaryFile` and streams data directly from S3 into the Gzip compression stream (each S3 object is read in ≤64 KiB chunks).

  * **Why?** This approach is highly memory-efficient, as the Lambda never needs to load entire source files into memory. This allows us to keep the Lambda’s memory setting (and therefore cost) low.

### 4\. Static Analysis with Strict Type Hinting

We use comprehensive type hints and enforce them with `mypy --strict` in our CI/CD pipeline.

  * **Why?** This makes the code more self-documenting and allows static analysis tools to catch a whole class of potential bugs before the code is ever deployed.

## 🧪 Development & Testing

This project uses `pytest` for unit testing. The architecture allows for extensive mocking of external services.

```bash
# Run the unit test suite
pytest
```

## Performance & Cost Optimization

Lambda performance is allocated proportionally to the memory setting. For this function, which performs multiple S3 I/O operations, a higher memory setting can reduce execution time.

**Guidance:** **512 MB** provides a good balance of performance and cost. Use the [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) tool to validate this for production traffic.

## 🔭 Observability & Monitoring

The function is instrumented with `aws-lambda-powertools`. The following are critical alarms to configure:

  * **SQS Queue Depth:** An alarm on `ApproximateAgeOfOldestMessage` for the main SQS queue will alert on processing backlogs.
  * **DLQ Messages:** An alarm on `NumberOfMessagesVisible` for the Dead-Letter Queue is essential for detecting persistent processing failures.
  * **Distribution Bucket Size:** An alarm on `NumberOfObjects` for the S3 Distribution Bucket will alert if the on-premise service stops consuming files.
  * **Lambda Errors:** Standard alarms on the `Errors` and `Throttles` metrics for the Lambda function.

## ⚙️ Environment Variables

The function requires the following environment variables to be set:

| Variable                   | Required/Default | Description                                                | Example Value                              |
|:---------------------------|:-----------------|:-----------------------------------------------------------|:-------------------------------------------|
| `IDEMPOTENCY_TABLE_NAME`   | **Required**     | The name of the DynamoDB table for idempotency tracking.   | `data-aggregator-prod-idempotency-table`   |
| `ARCHIVE_BUCKET_NAME`      | **Required**     | The name of the S3 bucket where Gzip bundles are archived. | `data-aggregator-prod-archive-bucket`      |
| `DISTRIBUTION_BUCKET_NAME` | **Required**     | The name of the S3 bucket for the consumer to pull from.   | `data-aggregator-prod-distribution-bucket` |
| `IDEMPOTENCY_TTL_DAYS`     | Default: `7`     | Retention period in days for idempotency keys.             | `7`                                        |
| `DYNAMODB_TTL_ATTRIBUTE`   | Default: `ttl`   | Name of the TTL attribute in the idempotency table.        | `ttl`                                      |
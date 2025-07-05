# Data Aggregator Lambda

This AWS Lambda function is a core component of the real-time data ingestion pipeline. It is triggered by SQS messages originating from S3 object creation events.

## Project Overview

The function's primary responsibilities are to:
1.  **Consume** S3 object creation events from an SQS queue in batches.
2.  **Filter** out duplicate events using a DynamoDB table for idempotency.
3.  **Aggregate** the content of multiple data files into a single, compressed Gzip bundle.
4.  **Archive** this canonical Gzip bundle to a long-term S3 archive bucket.
5.  **Deliver** the bundle securely to an on-premise NiFi endpoint.
6.  **Handle** downstream outages using a robust, self-healing Circuit Breaker.

## 🗂️ File Structure

The function is intentionally split into three top-level modules to enforce a clear separation of concerns, which is critical for testability and maintainability.

*   `app.py`: **The Orchestrator / Lambda Adapter**. This is the main entry point for the AWS Lambda service. Its job is to handle the event/context, manage dependencies, and orchestrate the calls between the other modules. It contains all the "Lambda-specific" code.
*   `core.py`: **The Pure Business Logic**. This module contains the core algorithm for creating the Gzip bundle. It has no knowledge of AWS, Lambda, or SQS. It's pure, portable Python, making it extremely easy to unit-test.
*   `clients.py`: **The I/O / Integration Layer**. This module contains wrappers (façades) for all external services (S3, DynamoDB, NiFi). It isolates the rest of the application from the implementation details of `boto3` and `requests`.

## 🏛️ Design Philosophy & Key Patterns

The structure of `app.py` was carefully chosen to maximize testability, robustness, and maintainability, adhering to modern serverless best practices.

### 1. Statelessness & Per-Invocation Dependencies

The `Dependencies` class is instantiated inside the `handler` function, not at the global module level.

*   **Why?** This is a critical design choice for robustness. AWS Lambda may reuse a "warm" container for multiple invocations. By creating a fresh `Dependencies` instance every time, we guarantee each invocation is stateless and isolated, ensuring the function always fetches the latest configuration (e.g., secrets). Re-instantiating is inexpensive, as `aws-lambda-powertools`' `SecretsProvider` reuses a thread-safe, region-level cache, so duplicate network calls are avoided even with fresh `Dependencies()` objects.

### 2. Explicit Dependency Injection (DI)

We use a factory function, `make_record_handler(dependencies: Dependencies)`, to supply the per-message processor with the dependencies it needs.

*   **Why?** This makes dependencies explicit. A function's signature tells you exactly what it needs to do its job. For testing, we can easily create a mock `Dependencies` object and pass it into our functions, giving us complete control over the test environment without complex patching.

### 3. Memory-Efficient & Resilient Streaming

The `core.py` module uses `SpooledTemporaryFile` and streams data directly from S3 into the Gzip compression stream (each S3 object is read in ≤64 KiB chunks).

*   **Why?** This approach is highly memory-efficient, as the Lambda never needs to load entire source files into memory. This lets us keep the Lambda’s memory setting (and therefore cost) low. It also improves resilience by minimizing the time spent holding an open connection to NiFi, reducing the window for network back-pressure to cause timeouts.

### 4. Self-Healing Circuit Breaker

The `CircuitBreakerClient` protects the system from cascading failures when the downstream NiFi endpoint is unavailable.

*   **Why?** It prevents the function from repeatedly hammering a failing endpoint, which saves cost and prevents log spam. The client stores state in DynamoDB and automatically transitions from **OPEN → HALF_OPEN** after a 5-minute cooldown, allowing the system to detect recovery and self-heal without manual intervention.

### 5. Static Analysis with Strict Type Hinting

We use comprehensive type hints, including `TypeAlias` (requires Python 3.10+), and enforce them with `mypy --strict` in our CI/CD pipeline.

*   **Why?** This makes the code more self-documenting and allows static analysis tools to catch a whole class of potential bugs before the code is ever deployed, improving the long-term health and maintainability of the project.

## 🧪 Development & Testing

This project uses `pytest` for unit testing. The architecture allows for extensive mocking of external services.

```bash
# Run the unit test suite
pytest
```

For a faster feedback loop during development, use `pytest-watch` to automatically re-run tests on file changes: `ptw`.

For local integration testing against simulated cloud services, you can use frameworks like `LocalStack` or `moto`.

## Performance & Cost Optimization

Lambda performance (CPU, network bandwidth) is allocated proportionally to the memory setting. For this function, which performs both S3 downloads and HTTP uploads, a higher memory setting can significantly reduce execution time.

**Guidance:** Testing has shown that **512 MB** provides a good balance of performance and cost for the expected workload. Use the [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) tool to validate the optimal setting for your specific production traffic patterns.

## 🔭 Observability & Monitoring

The function is instrumented with `aws-lambda-powertools` for structured logging (`Logger`), distributed tracing (`Tracer`), and custom metrics (`Metrics`). The following are critical alarms to configure:

*   **SQS Queue Depth:** An alarm on `ApproximateAgeOfOldestMessage` for the main SQS queue will alert on processing backlogs.
*   **DLQ Messages:** An alarm on `NumberOfMessagesVisible` for the Dead-Letter Queue is essential for detecting poison-pill messages or persistent processing failures.
*   **Circuit Breaker State:** Add a CloudWatch alarm on the `CircuitBreakerOpen` custom metric (emitted via Powertools Metrics) to get an immediate alert for downstream outages.
*   **Lambda Errors:** Standard alarms on the `Errors` and `Throttles` metrics for the Lambda function itself.

## ⚙️ Environment Variables

The function requires the following environment variables to be set:

| Variable                     | Required/Default | Description                                                   | Example Value                                     |
|------------------------------|------------------|---------------------------------------------------------------|---------------------------------------------------|
| `IDEMPOTENCY_TABLE_NAME`     | **Required**     | The name of the DynamoDB table for idempotency tracking.      | `data-aggregator-prod-idempotency-table`          |
| `IDEMPOTENCY_TTL_DAYS`       | Default: `7`     | Retention period in days for idempotency keys.                | `7`                                               |
| `ARCHIVE_BUCKET_NAME`        | **Required**     | The name of the S3 bucket where Gzip bundles are archived.    | `data-aggregator-prod-archive-bucket-a1b2c3d4`    |
| `NIFI_ENDPOINT_URL`          | **Required**     | Full URL of the on-premise NiFi HTTP ingest endpoint.         | `https://nifi.onprem.example.com/contentListener` |
| `NIFI_SECRET_ARN`            | **Required**     | ARN of the AWS Secrets Manager secret with NiFi credentials.  | `arn:aws:secretsmanager:eu-west-2:123...`         |
| `CIRCUIT_BREAKER_TABLE_NAME` | **Required**     | The name of the DynamoDB table for the circuit breaker state. | `data-aggregator-prod-circuit-breaker-table`      |
| `DYNAMODB_TTL_ATTRIBUTE`     | Default: `ttl`   | Name of the TTL attribute in the idempotency table.           | `ttl`                                             |
# Code Design & Implementation Guide: Data Aggregation Pipeline

This document provides a detailed overview of the pipeline's code structure, design patterns, and the rationale behind key implementation decisions.

-----

## 1\. High-Level Architecture

The system is a fully serverless, event-driven pipeline on AWS. It ingests a high volume of small files from S3, uses an SQS queue to decouple ingestion from processing, and triggers a Lambda function to perform idempotent aggregation and secure delivery to an on-premise MinIO instance.

```mermaid
flowchart TD
    %% ───────── Nodes ─────────
    subgraph "On-Premise Data Center"
        MinIO["MinIO Instance"]
    end
    
    subgraph "AWS Cloud (eu-west-2)"
        SecretsManager["Secrets Manager"]
        Lambda["Aggregator Lambda"]
        ExternalParty["External Party"]
        S3["S3 Bucket"]
        SQS["SQS Queue"]
        DLQ["Dead-Letter Queue"]
        DynamoDB["Idempotency Table"]
        CloudWatch["CloudWatch<br/>Metrics & Alarms"]
    end

    %% ───────── Edges ─────────
    ExternalParty -->| "1 - Uploads files (HTTPS)" | S3
    S3            -->| "2 - Event notification"  | SQS
    SQS           -->  "Auto-scales based on queue depth"  --> Lambda
    Lambda        -->| "3 - Triggered with batch" | SQS
    Lambda        -->| "4 - Checks & updates keys" | DynamoDB
    Lambda        -->| "5 - Downloads files" | S3
    SecretsManager -->| "6 - Provides credentials" | Lambda
    Lambda        -->| "7 - Pushes metrics" | CloudWatch
    Lambda        -->| "8 - Pushes batch (via private network)" | MinIO
    SQS           -->| "Persistent failure" | DLQ

    %% ───────── Styling ─────────
    classDef orange fill:#FF9900,stroke:#333,stroke-width:2px;
    classDef pink   fill:#FF4F8B,stroke:#333,stroke-width:2px;
    classDef blue   fill:#4DA4DB,stroke:#333,stroke-width:2px;
    classDef red    fill:#CC0000,stroke:#333,stroke-width:2px;

    class Lambda,S3 orange;
    class SQS pink;
    class DynamoDB blue;
    class DLQ red;
```

-----

## 2\. Detailed Code Implementation & Patterns

This section details the implementation of each module, explaining how the code works and the design patterns chosen.

### 2.1. `app.py`: The Orchestrator

This module is the heart of the application, responsible for orchestrating the entire workflow within the Lambda handler.

#### **Handler and Batch Processing (`handler`)**

  * **Pattern:** The handler uses the **AWS Lambda Powertools `BatchProcessor`**.
  * **What it does:** The `handler` function receives the raw SQS event. Instead of manually looping through records, it passes the entire event to the `BatchProcessor`. This processor iterates over each message, calling our custom `collect_s3_keys` function for each one.
  * **Why this pattern was chosen:**
      * **Resilience:** The `BatchProcessor` automatically handles partial failures. If one message in a batch fails (e.g., malformed JSON), it is marked for retry, and the processor continues with the rest of the batch. This prevents a single "poison pill" message from blocking the entire pipeline.
      * **Simplicity:** It abstracts away the complex boilerplate of message deletion, error tracking, and response formatting, making the main handler logic cleaner and focused on business rules.
      * **Security:** We configure the Powertools Logger with `log_event=False` to prevent the raw SQS message content from being logged in production, reducing the risk of sensitive data exposure.

#### **Concurrent Archiving (`stream_archive_to_minio`)**

  * **Pattern:** This function uses a **multi-threaded producer-consumer model** to build the archive.
  * **What it does:**
    1.  **Producers (`_fetcher` threads):** A `ThreadPoolExecutor` spawns multiple `_fetcher` threads (up to `MAX_FETCH_WORKERS`). Each thread is responsible for downloading a single file from S3. Instead of reading the file into memory, it gets a `StreamingBody` object.
    2.  **Bounded Queue (`data_queue`):** The `StreamingBody` objects are placed into a `queue.Queue` that has its size capped to `MAX_FETCH_WORKERS`. This is a critical **back-pressure mechanism** that prevents the fetcher threads from downloading files faster than they can be processed, which would otherwise consume excessive memory.
    3.  **Consumer (`_writer` thread):** A single `_writer` thread consumes items from the queue. It reads from each `StreamingBody` and writes the data directly into a `tarfile` stream, which compresses the data on the fly.
  * **Why this pattern was chosen:**
      * **Performance:** Parallelizing the S3 downloads is the single biggest performance gain, as it overlaps the network I/O wait times.
      * **Memory Efficiency:** Streaming data directly from S3 through the tarball compressor, without holding entire files in memory, allows the function to handle large archives with a small memory footprint. The use of `tempfile.SpooledTemporaryFile` further optimizes this by keeping small archives entirely in memory and only using disk for large ones.
      * **Robustness:** The logic includes dynamic timeouts based on the remaining Lambda execution time and graceful shutdown signals (`error_event`), ensuring the function can handle errors and timeouts without leaving orphaned threads or leaking resources.

#### **Data Integrity and Upload**

  * **Pattern:** A **two-step checksum verification** process is used.
  * **What it does:**
    1.  The `ArchiveHasher` class wraps the archive stream, calculating a SHA256 hash as the data is read during the `upload_fileobj` call.
    2.  After the upload completes, the final digest is retrieved from the `hasher`.
    3.  A lightweight, server-side `copy_object` call is made to atomically add the correct checksum as `x-amz-meta-sha256_checksum` to the object's metadata.
  * **Why this pattern was chosen:**
      * **Correctness:** This is the only pattern that guarantees the checksum is of the *entire* streamed file without reading it into memory twice. It solves the logical conflict of needing the final digest before the stream that generates it has finished.
      * **Visibility:** Storing the checksum in primary object metadata makes it easily accessible to any standard S3/MinIO tool or for automated auditing, which would not be true if object tags were used.

### 2.2. `core.py`: Pure & Testable Business Logic

This module contains stateless functions that are decoupled from AWS services, making them easy to unit-test.

  * **Pattern:** Idempotency is achieved using **atomic, conditional database writes**.
  * **What it does:** The `is_object_unique` function takes an S3 object key and attempts to write it to DynamoDB. The `put_item` call includes `ConditionExpression="attribute_not_exists(ObjectID)"`.
  * **Why this pattern was chosen:**
      * **Atomicity:** This condition expression makes the check-and-set operation atomic. It is impossible for two concurrent Lambda invocations to both think the same key is "new," which prevents race conditions and data duplication.
      * **Performance at Scale:** To prevent "hot partitions" in DynamoDB, the partition key is **sharded** by prepending a 4-character hash of the S3 key (e.g., `a4f1#path/to/file.txt`). This ensures that writes are distributed evenly across DynamoDB's underlying infrastructure, maintaining high performance even with sequential, time-based S3 keys.

### 2.3. `clients.py`: Dependency Management Factory

This module provides a centralized and consistent way to create AWS service clients.

  * **Pattern:** It implements the **Factory** design pattern for dependency injection.
  * **What it does:** The `get_boto_clients` function creates a `boto3.Session` and uses it to generate all required clients (S3, SQS, DynamoDB, etc.).
  * **Why this pattern was chosen:**
      * **Consistency:** All clients are created with a shared, resilient retry configuration (`BOTO_CONFIG_RETRYABLE`), ensuring consistent behavior across all AWS interactions.
      * **Testability:** The module includes a crucial **safety guardrail** that raises an error if the `USE_MOTO` environment variable (used for mocking during tests) is detected in a production environment.
      * **Maintainability:** Centralizing client creation makes the code easier to maintain. If a new global configuration (like a custom endpoint or credential provider) is needed, it only needs to be changed in this one place.
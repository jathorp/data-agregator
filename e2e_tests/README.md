# Data Aggregator - End-to-End Test Suite

This directory contains the end-to-end (E2E) test suite for the Data Aggregator Lambda function. These tests are designed to validate the behavior of the entire deployed system, from S3 object creation through SQS and Lambda processing, to the final bundle creation.

##  Philosophy

While unit tests validate individual functions in isolation, these E2E tests validate the **interactions and configuration of the entire system**. They are designed to answer questions that unit tests cannot:

-   **Permissions:** Does the Lambda's IAM Role have the correct permissions to all required services (S3, SQS, DynamoDB)?
-   **Infrastructure:** Are the S3 event notifications, SQS triggers, and Lambda event source mappings configured correctly?
-   **Integration:** Does the Powertools `@idempotent` decorator behave as expected against a real DynamoDB table?
-   **Resilience:** Does the system gracefully handle partial batch failures, deleted files, and invalid inputs?
-   **Performance:** Can the system handle high-volume and high-concurrency workloads without data loss?

## ⚙️ Prerequisites

1.  **Deployed AWS Infrastructure:** These tests run against a live, deployed AWS environment provisioned via Terraform.
2.  **AWS Credentials:** Your local environment must be configured with AWS credentials that have permissions to interact with the test resources (S3, Lambda).
3.  **Python Environment:** A Python 3.9+ virtual environment is required.
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

## 🚀 How to Run Tests

All tests are executed via the `main.py` script and driven by JSON configuration files.

### Basic Usage

The primary command structure is:

```bash
python main.py --config <path_to_config_file.json>
```

**Common Flags:**
*   `-c, --config`: (Required) Path to the JSON configuration file for the desired test case.
*   `-v, --verbose`: Enable verbose output, including full exception tracebacks for debugging.

### Examples

**Running a simple sanity check:**
```bash
python main.py --config configs/config_00_singe_file.json
```

**Running the complex partial batch failure test with verbose logging:**
```bash
python main.py --config configs/config_12_test_large_files.json --verbose
```

The runner will output progress to the console and generate a JUnit XML report if specified in the config file. A return code of `0` indicates success.

## 🧪 Test Suite Overview

The suite is composed of multiple, targeted test cases, each defined by a JSON configuration file.

| Test File                             | Description                                                                                                                                                     | Key Validations                                                               |
|:--------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------|:------------------------------------------------------------------------------|
| `config_00_singe_file.json`          | A simple "smoke test" that uploads and validates a single file.                                                                                                 | Baseline functionality of the entire pipeline.                                |
| `config_01_batching.json`            | Uploads a medium number of small files to ensure the Lambda can process a full batch from SQS.                                                                  | SQS batching, basic bundling logic.                                           |
| `config_02_large_file.json`          | Uploads a single file larger than the 64MB in-memory spooling threshold.                                                                                        | Correct handling of large files and spilling to ephemeral disk.               |
| `config_03_zero_byte.json`           | Verifies that the system can correctly handle and bundle zero-byte source files without errors.                                                                 | Edge case handling.                                                           |
| `config_04_concurrency.json`         | Stresses the system with high-concurrency uploads to test Lambda scaling and idempotency under load.                                                            | System stability, idempotency at scale.                                       |
| `config_05_compressible.json`        | Uses highly repetitive text data to validate that the `gzip` compression is working effectively.                                                                | Core bundling and compression logic.                                          |
| `config_06_disk_limit.json`          | (`direct_invoke`) Deterministically tests the `MAX_BUNDLE_ON_DISK_BYTES` guardrail by sending a payload that exceeds the limit.                                 | Internal guardrails, graceful processing limits.                              |
| `config_07_idempotency.json`         | (`idempotency_check`) Validates the core business logic for versioning. Uploads a file, then overwrites it, confirming both versions are processed.             | Version-aware idempotency strategy (`versionId` in key).                      |
| `config_08_backlog.json`             | Simulates clearing a massive backlog by uploading thousands of files at high concurrency.                                                                       | High-throughput performance and scalability.                                  |
| `config_09_memory_pressure.json`     | (`memory_pressure`) Tests Lambda memory limit handling by processing files sized to stay in memory and push Lambda close to its 512MB memory limit.            | Memory pressure handling, `MemoryLimitError` exception handling.              |
| `config_10_file_not_found.json`      | (`file_not_found`) Simulates a race condition by deleting a file after its SQS event is created.                                                                | `ObjectNotFoundError` exception handling, resilience.                         |
| `config_11_key_sanitization.json`    | (`key_sanitization`) Tests security by uploading a file with a `../` path traversal attempt in its key.                                                         | S3 key normalization handling and `_sanitize_s3_key` transformation logic.    |
| `config_12_test_large_files.json`    | (`partial_batch_failure`) Deterministically triggers the SQS partial batch failure mechanism by sending files that force the bundle limit to be hit repeatedly. | **The most critical resilience test.** Validates the SQS retry feedback loop. |

## 🏗️ Architecture of the Test Runner

The test runner is composed of several key components:

-   `main.py`: The main entry point that parses arguments and orchestrates the run.
-   `components/config.py`: A `dataclass`-based module for loading and validating test parameters from the JSON files.
-   `components/pre_flight.py`: Performs initial checks to verify AWS connectivity and access to required resources, failing fast before tests begin.
-   `components/data_generator.py`: An abstract class for creating test data, with concrete implementations for random (incompressible) and text (compressible) data.
-   `components/runner.py`: The core orchestrator. It executes a test in three main phases:
    1.  **Produce:** Generates local source files and uploads them to the landing bucket in a tight window to encourage SQS batching.
    2.  **Consume:** Polls the distribution bucket, downloading and extracting all bundles until every file expected in the test manifest is found.
    3.  **Validate:** Compares the SHA256 hashes of the extracted files against the manifest to guarantee data integrity.

## ✏️ Adding a New Test Case

To add a new test case (e.g., Test 13):

1.  **Create the Config File:** Create `config_13_my_new_test.json`. Define its parameters, including a clear `description`.
2.  **Choose a `test_type`:**
    -   If it's a standard S3-triggered test, you can likely reuse `test_type: "s3_trigger"` (the default).
    -   If it requires special orchestration (like deleting a file), create a new, descriptive `test_type` (e.g., `"my_special_test"`).
3.  **Implement the Runner Logic (if needed):**
    -   If you created a new `test_type`, open `components/runner.py`.
    -   Create a new private method named `_run_my_special_test(self) -> int`.
    -   Add a new `elif self.config.test_type == "my_special_test":` block to the main `run()` method to call your new function.
4.  **Update this README:** Add your new test case to the overview table to keep the documentation current.

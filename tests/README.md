## Testing Strategy for Powertools-Enhanced Lambda Functions

This document outlines the best-practice testing strategy for our AWS Lambda functions, particularly those using decorators from **AWS Powertools for Python**. Our goal is to create a suite of fast, reliable, and maintainable tests that give us full confidence in our code.

Our approach is based on a three-tiered model:

1.  **Unit Test Business Logic**: Test the code we write, completely isolated from Powertools.
2.  **Unit Test Decorator Behavior**: Test our specific configuration of the Powertools decorator, ensuring it behaves as expected under various conditions.
3.  **Integration Test the Whole System**: Run a smoke test against a near-real environment to catch configuration and serialization errors.

-----

### Part 1: Unit Testing Your Core Business Logic

For any function decorated with `@idempotent`, we need a fast unit test to verify its internal logic.

**Strategy:**
Use the `POWERTOOLS_IDEMPOTENCY_DISABLED` environment variable to completely bypass the decorator. This is the simplest, officially recommended way to isolate and test your business logic as a plain Python function.

**Implementation:**

1.  **Use a fixture** to manage the environment variable. This ensures it's set for the specific test and automatically cleaned up afterwards, preventing bleed-through into other tests.
2.  Mock the direct dependencies of your business logic (e.g., the `boto3` calls made *inside* your function).
3.  Call the handler and assert that it returns the correct result.

**Example (`tests/unit/test_handler_logic.py`):**

```python
import pytest
from unittest.mock import MagicMock, patch

# 1. Use a fixture for clean setup and teardown
@pytest.fixture
def idempotency_disabled_env(monkeypatch):
    """Disables the idempotency utility for a single test."""
    monkeypatch.setenv("POWERTOOLS_IDEMPOTENCY_DISABLED", "true")
    yield
    monkeypatch.delenv("POWERTOOLS_IDEMPOTENCY_DISABLED")

def test_handler_logic_with_idempotency_disabled(
    sqs_event, lambda_context, idempotency_disabled_env
):
    """Tests the core business logic with the idempotency feature disabled."""
    # 2. Mock the function's direct dependencies
    mock_ddb_table = MagicMock()
    mock_boto3_resource = MagicMock()
    mock_boto3_resource.Table.return_value = mock_ddb_table

    with patch("data_aggregator.app.boto3.resource", return_value=mock_boto3_resource):
        # Must import handler *after* mocks and env vars are set
        from data_aggregator.app import lambda_handler

        # 3. Call the handler and assert results
        result = lambda_handler(sqs_event, lambda_context)

    assert result["status"] == "processed"
    mock_ddb_table.put_item.assert_called_once()
```

-----

### Part 2: Unit Testing the `@idempotent` Decorator's Behavior

This is the most critical test for preventing duplicate processing. The goal is to simulate duplicate invocations and confirm our core logic does **not** run a second time.

**Strategy:**
Let the real `DynamoDBPersistenceLayer` be created, but inject a mocked `boto3` client into it using `botocore.stub.Stubber`. The `Stubber` provides strict request/response validation, making our tests more precise and resilient than a bare `MagicMock`.

**Implementation:**
We use the `Stubber` to tell a consistent story about the state of DynamoDB.

1.  **Use Public Constants**: Import `Status` from Powertools instead of using "magic strings" like `"COMPLETED"`.
2.  **Mock Business Logic**: Patch your core business logic function so you can track its call count.
3.  **Simulate the First Call**: Stub a successful `put_item` call and assert your logic was called once.
4.  **Simulate the Second Call**:
      * **Stub `put_item` Failure**: The stubber will expect a `put_item` call and respond with a `ConditionalCheckFailedException`. This perfectly mimics DynamoDB's response when an item with the same key already exists.
      * **Stub `get_item` Success**: The stubber will then expect a `get_item` call and return a valid, **non-expired** DynamoDB item with a `status` of `Status.COMPLETED.value`.
5.  **Assert Idempotency**: Call the handler a second time. Assert that your business logic was **NOT** called, and that the handler returned the saved result.

**Example (`tests/unit/test_handler_idempotency.py`):**

```python
# In tests/unit/test_handler_idempotency.py
import time
import json
from unittest.mock import patch

# IMPORTANT: Import boto3, Stubber, and the Status enum
import boto3
from botocore.stub import Stubber
from aws_lambda_powertools.utilities.idempotency.persistence import Status

# Import your app components
from data_aggregator.app import persistence_layer, lambda_handler

def test_handler_is_idempotent_with_stubber(sqs_event, lambda_context):
    """Tests the idempotency decorator by stubbing Boto3 calls."""
    # Mock the business logic to isolate the test to the decorator
    saved_result = {"status": "processed", "messageId": "12345-67890"}
    mock_process_message = patch("data_aggregator.app.process_message", return_value=saved_result).start()

    # Create a dummy client for the stubber to wrap.
    # This avoids needing real credentials in a unit test.
    dummy_boto3_client = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="dummy",
        aws_secret_access_key="dummy"
    )

    with Stubber(dummy_boto3_client) as stubber:
        # Inject the stubbed client into the real persistence layer
        persistence_layer.client = dummy_boto3_client

        # --- SIMULATE THE FIRST CALL ---
        # A successful invocation makes a put_item, then an update_item.
        stubber.add_response("put_item", {})
        stubber.add_response("update_item", {}) # This reflects the real behavior
        
        lambda_handler(sqs_event, lambda_context)
        mock_process_message.assert_called_once()
        stubber.assert_no_pending_responses() # Verify all stubs were used

        mock_process_message.reset_mock()

        # --- SIMULATE THE SECOND CALL ---
        # a) Stub put_item to fail as if the record already exists
        stubber.add_client_error(
            "put_item",
            service_error_code="ConditionalCheckFailedException",
        )
        # b) Stub get_item to return the previously saved record
        future_timestamp = int(time.time()) + 3600
        dynamodb_item_response = {
            'Item': {
                'id': {'S': 'some-idempotency-key'},
                'data': {'S': json.dumps(saved_result)},
                'status': {'S': Status.COMPLETED.value}, # Use the enum value
                'expiration': {'N': str(future_timestamp)}
            }
        }
        stubber.add_response("get_item", dynamodb_item_response)

        # --- ASSERT IDEMPOTENCY ---
        second_call_result = lambda_handler(sqs_event, lambda_context)
        stubber.assert_no_pending_responses()

        # Assert: Business logic was NOT called, and saved result was returned
        mock_process_message.assert_not_called()
        assert second_call_result == saved_result
    
    patch.stopall() # Clean up the patch for "process_message"
```
-----

### Part 3: Advanced and Integration Testing

For mission-critical applications, unit tests should be supplemented with tests for edge cases and real-world integration.

#### Testing for Concurrency (`IN_PROGRESS` status)

Idempotency bugs often appear during concurrent executions. This test ensures you are protected from race conditions.

```python
import pytest
from aws_lambda_powertools.utilities.idempotency import IdempotencyInProgressError
from aws_lambda_powertools.utilities.idempotency.persistence import Status

def test_handler_handles_in_progress_state(sqs_event, lambda_context):
    """Tests that the handler raises IdempotencyInProgressError for concurrent executions."""
    real_boto3_client = boto3.client("dynamodb")
    with Stubber(real_boto3_client) as stub:
        persistence_layer.client = real_boto3_client

        # Simulate that another invocation has already started processing
        in_progress_response = {
            'Item': {
                'id': {'S': 'some-idempotency-key'},
                'status': {'S': Status.IN_PROGRESS.value},
                'expiration': {'N': str(int(time.time()) + 60)}
            }
        }
        stub.add_client_error("put_item", "ConditionalCheckFailedException")
        stub.add_response("get_item", in_progress_response)
        
        # Assert that our handler correctly raises the in-progress error
        with pytest.raises(IdempotencyInProgressError):
            lambda_handler(sqs_event, lambda_context)
```

#### Integration Smoke Testing

Unit tests can't catch everything. An integration test against a local or ephemeral AWS environment catches IAM misconfigurations, JSON serialization issues, and other configuration drift.

  * **Location**: Place these in a separate `tests/integration/` folder.
  * **Execution**: Mark them with `@pytest.mark.integration` and run them separately from your fast unit tests.
  * **Strategy**: No mocks. Point the test at a real resource, like DynamoDB Local running in a Docker container.

<!-- end list -->

```python
# tests/integration/test_full_flow.py
import pytest

# This marker allows us to run integration tests separately
@pytest.mark.integration
def test_handler_against_real_dynamodb(sqs_event, lambda_context):
    """An end-to-end test against a local DynamoDB instance."""
    # In CI, this would point to DynamoDB Local or a deployed dev table
    # No mocks are used here.
    
    from data_aggregator.app import lambda_handler

    # First call should succeed and write to the DB
    result1 = lambda_handler(sqs_event, lambda_context)
    assert result1['status'] == 'processed'

    # Second call should be idempotent
    result2 = lambda_handler(sqs_event, lambda_context)
    assert result2 == result1 # Should return the same result
```
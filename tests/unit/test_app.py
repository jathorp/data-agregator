# tests/unit/test_app.py

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# Before importing the app, we must patch the environment variables
MOCK_ENV = {
    "IDEMPOTENCY_TABLE_NAME": "test-idempotency-table",
    "ARCHIVE_BUCKET_NAME": "test-archive-bucket",
    "DISTRIBUTION_BUCKET_NAME": "test-distribution-bucket",
    "POWERTOOLS_LOG_LEVEL": "INFO",
}

# Use patch.dict to set the environment variables before the app module is imported
with patch("boto3.client") as mock_boto_client:
    # We still need to patch the environment for the app's own config loading
    with patch.dict(os.environ, MOCK_ENV):
        from src.data_aggregator import app
        from src.data_aggregator.app import (
            Dependencies,
            make_record_handler,
            _process_successful_batch,
            SQSBatchProcessingError,
            TransientDynamoError,
            BatchTooLargeError,
        )



# --- Fixtures ---

@pytest.fixture
def mock_lambda_context():
    """Provides a mock LambdaContext object."""
    context = MagicMock()
    context.aws_request_id = "test-request-id-123"
    context.get_remaining_time_in_millis.return_value = 300_000
    return context

@pytest.fixture
def mock_dependencies():
    """Provides a mock Dependencies container with mocked clients."""
    deps = MagicMock(spec=Dependencies)
    deps.dynamodb_client = MagicMock()
    deps.s3_client = MagicMock()
    return deps

def create_sqs_record(message_id, key, size):
    """Helper function to create a valid SQS record for tests."""
    s3_event = {"Records": [{"s3": {"object": {"key": key, "size": size}}}]}
    return MagicMock(
        message_id=message_id,
        body=json.dumps(s3_event)
    )


# --- Tests for record_handler ---

def test_record_handler_new_key(mock_dependencies):
    """
    Verifies the handler processes a new key correctly.
    """
    # Arrange
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg1", "new-file.txt", 1024)
    # Mock that the key is new
    mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = True

    # Act
    result = handler(record)

    # Assert
    # Check that the idempotency client was called correctly
    mock_dependencies.dynamodb_client.check_and_set_idempotency.assert_called_once()
    # Check that the result is the parsed S3 event record
    assert result["s3"]["object"]["key"] == "new-file.txt"


def test_record_handler_duplicate_key(mock_dependencies):
    """
    Verifies the handler correctly skips a duplicate key.
    """
    # Arrange
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg2", "duplicate-file.txt", 1024)
    # Mock that the key already exists
    mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = False

    # Act
    result = handler(record)

    # Assert
    # The result for a duplicate should be an empty dictionary
    assert result == {}


def test_record_handler_dynamodb_error_raises_transient_error(mock_dependencies):
    """
    Verifies that a ClientError from DynamoDB is wrapped in a custom exception.
    """
    # Arrange
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg3", "any-file.txt", 1024)
    # Mock a generic boto3 ClientError
    mock_dependencies.dynamodb_client.check_and_set_idempotency.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem"
    )

    # Act & Assert
    with pytest.raises(TransientDynamoError):
        handler(record)

# --- Tests for _process_successful_batch ---

@patch("src.data_aggregator.app.process_and_stage_batch")
def test_process_successful_batch_happy_path(mock_core_processor, mock_lambda_context, mock_dependencies):
    """
    Verifies that the core bundling logic is called for a valid batch.
    """
    # Arrange
    s3_record = {"s3": {"object": {"key": "file.txt", "size": 5000}}}

    # Create a mock that has the same shape as the real result object.
    successful_records = [s3_record]

    # Act
    _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)

    # Assert
    mock_core_processor.assert_called_once()
    call_args = mock_core_processor.call_args[1]
    assert call_args["records"] == [s3_record]
    assert call_args["archive_key"] == "bundle-test-request-id-123.gz"


@patch("src.data_aggregator.app.process_and_stage_batch")
def test_process_successful_batch_raises_for_large_batch(mock_core_processor, mock_lambda_context, mock_dependencies):
    """
    Verifies that a BatchTooLargeError is raised if input size exceeds the limit.
    """
    # Arrange
    large_size = 101 * 1024 * 1024
    s3_record = {"s3": {"object": {"key": "large-file.txt", "size": large_size}}}

    successful_records = [s3_record]

    # Act & Assert
    with pytest.raises(BatchTooLargeError):
        _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)
    mock_core_processor.assert_not_called()

# --- Tests for the main handler (integration of components) ---

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.make_record_handler")
def test_handler_full_success(mock_make_handler, mock_process_batch, mock_lambda_context):
    """
    Tests the main handler for a batch where all records succeed.
    """
    # Arrange
    # Mock the record handler to always return success
    mock_handler_func = MagicMock(return_value={"s3": "...record..."})
    mock_make_handler.return_value = mock_handler_func

    sqs_event = {
        "Records": [
            {"messageId": "msg1", "body": "{...}"},
            {"messageId": "msg2", "body": "{...}"},
        ]
    }

    # Act
    result = app.handler(sqs_event, mock_lambda_context)

    # Assert
    # The handler should have been called for each record
    assert mock_handler_func.call_count == 2
    # The batch processing logic should have been called once
    mock_process_batch.assert_called_once()
    # No failures should be reported back to SQS
    assert result["batchItemFailures"] == []


@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.make_record_handler")
def test_handler_batch_level_failure(mock_make_handler, mock_process_batch, mock_lambda_context):
    """
    Tests that if the batch processing fails, all successful records are marked for retry.
    """
    # Arrange
    mock_handler_func = MagicMock(return_value={"s3": "...record..."})
    mock_make_handler.return_value = mock_handler_func
    # Mock the batch processor to raise a retryable error
    mock_process_batch.side_effect = SQSBatchProcessingError("Retry the batch!")

    sqs_event = {
        "Records": [
            {"messageId": "msg1", "body": "{...}"},
            {"messageId": "msg2", "body": "{...}"},
        ]
    }

    # Act
    result = app.handler(sqs_event, mock_lambda_context)

    # Assert
    # All records should be marked as failures so SQS will retry them
    assert len(result["batchItemFailures"]) == 2
    assert result["batchItemFailures"][0]["itemIdentifier"] == "msg1"
    assert result["batchItemFailures"][1]["itemIdentifier"] == "msg2"
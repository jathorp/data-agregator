# tests/unit/test_app.py

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# --- Environment and Boto3 Patching ---
MOCK_ENV = {
    "IDEMPOTENCY_TABLE_NAME": "test-idempotency-table",
    "ARCHIVE_BUCKET_NAME": "test-archive-bucket",
    "DISTRIBUTION_BUCKET_NAME": "test-distribution-bucket",
    "POWERTOOLS_LOG_LEVEL": "INFO",
}

with patch("boto3.client"):
    with patch.dict(os.environ, MOCK_ENV, clear=True):
        from src.data_aggregator import app
        from src.data_aggregator.exceptions import SQSBatchProcessingError

# --- Fixtures ---

@pytest.fixture
def mock_lambda_context():
    """Provides a mock LambdaContext object."""
    context = MagicMock()
    context.aws_request_id = "test-request-id-123"
    return context

# --- Helper ---

def create_sqs_event(*records):
    """Creates a full SQS event from one or more record dictionaries."""
    return {"Records": list(records)}

def create_sqs_record_dict(message_id, key, size):
    """Creates a raw SQS record dictionary."""
    s3_event_body = {"Records": [{"s3": {"object": {"key": key, "size": size}}}]}
    return {"messageId": message_id, "body": json.dumps(s3_event_body)}

# --- New tests for the main handler ---

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.Dependencies")
def test_handler_new_records_are_bundled(mock_deps, mock_process_batch, mock_lambda_context):
    """
    Tests the happy path where new records are found and sent for bundling.
    """
    # Arrange
    # Mock the DynamoDB client to report that the key is new
    mock_deps.return_value.dynamodb_client.check_and_set_idempotency.return_value = True
    event = create_sqs_event(
        create_sqs_record_dict("msg1", "file1.txt", 100),
        create_sqs_record_dict("msg2", "file2.txt", 200),
    )

    # Act
    result = app.handler(event, mock_lambda_context)

    # Assert
    # Check that the bundling function was called
    mock_process_batch.assert_called_once()
    # Check that it received the correct, extracted S3 records
    called_with_records = mock_process_batch.call_args[0][0]
    assert len(called_with_records) == 2
    assert called_with_records[0]["s3"]["object"]["key"] == "file1.txt"
    # Check that no failures were reported to SQS
    assert result["batchItemFailures"] == []

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.Dependencies")
def test_handler_duplicates_are_skipped(mock_deps, mock_process_batch, mock_lambda_context):
    """
    Tests that if all records are duplicates, the bundling process is not triggered.
    """
    # Arrange
    # Mock the DynamoDB client to report that all keys are duplicates
    mock_deps.return_value.dynamodb_client.check_and_set_idempotency.return_value = False
    event = create_sqs_event(create_sqs_record_dict("msg1", "file1.txt", 100))

    # Act
    result = app.handler(event, mock_lambda_context)

    # Assert
    # The bundling function should NOT have been called
    mock_process_batch.assert_not_called()
    assert result["batchItemFailures"] == []

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.Dependencies")
def test_handler_malformed_message_is_reported_as_failure(mock_deps, mock_process_batch, mock_lambda_context):
    """
    Tests that a record with a non-JSON body is correctly marked as a failure.
    """
    # Arrange
    event = create_sqs_event({"messageId": "bad_msg", "body": "this-is-not-json"})

    # Act
    result = app.handler(event, mock_lambda_context)

    # Assert
    mock_process_batch.assert_not_called()
    assert len(result["batchItemFailures"]) == 1
    assert result["batchItemFailures"][0]["itemIdentifier"] == "bad_msg"

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.Dependencies")
def test_handler_batch_failure_retries_successful_items(mock_deps, mock_process_batch, mock_lambda_context):
    """
    Tests that if bundling fails, the records that were successfully processed
    in stage 1 are returned to SQS for a retry.
    """
    # Arrange
    # All records will be new initially
    mock_deps.return_value.dynamodb_client.check_and_set_idempotency.return_value = True
    # But the bundling process will fail
    mock_process_batch.side_effect = SQSBatchProcessingError("Bundling failed!")

    event = create_sqs_event(
        create_sqs_record_dict("msg1", "file1.txt", 100),
        create_sqs_record_dict("msg2", "file2.txt", 200),
    )

    # Act
    result = app.handler(event, mock_lambda_context)

    # Assert
    # The final failure list should contain the two successful messages for retry
    assert len(result["batchItemFailures"]) == 2
    assert result["batchItemFailures"][0]["itemIdentifier"] == "msg1"
    assert result["batchItemFailures"][1]["itemIdentifier"] == "msg2"
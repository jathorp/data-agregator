# tests/unit/test_app.py

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# --- Environment and Boto3 Patching ---
# This must happen BEFORE any application modules are imported.

MOCK_ENV = {
    "IDEMPOTENCY_TABLE_NAME": "test-idempotency-table",
    "ARCHIVE_BUCKET_NAME": "test-archive-bucket",
    "DISTRIBUTION_BUCKET_NAME": "test-distribution-bucket",
    "POWERTOOLS_LOG_LEVEL": "INFO",
}

# Patch boto3 to prevent NoRegionError during import, and patch the environment
# for the app's own configuration loading.
with patch("boto3.client"):
    with patch.dict(os.environ, MOCK_ENV, clear=True):
        from src.data_aggregator import app
        from src.data_aggregator.app import (
            Dependencies,
            make_record_handler,
            _process_successful_batch,
        )
        from src.data_aggregator.exceptions import (
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


# --- Helper Functions for Creating Test Data ---

def create_sqs_record(message_id, key, size):
    """Helper function to create a mock object that mimics a Powertools SQSRecord."""
    s3_event_body = {"Records": [{"s3": {"object": {"key": key, "size": size}}}]}
    # This mock has .message_id and .body attributes, just like the real object
    sqs_record = MagicMock()
    sqs_record.message_id = message_id
    sqs_record.body = json.dumps(s3_event_body)
    return sqs_record


def create_mock_success_message(message_id, result_data):
    """Creates a mock object that mimics the objects inside processor.success_messages."""
    message = MagicMock()
    message.message_id = message_id
    message.result = result_data  # This is the crucial part for the handler logic
    return message


# --- Tests for record_handler ---

def test_record_handler_new_key(mock_dependencies):
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg1", "new-file.txt", 1024)
    mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = True
    result = handler(record)
    mock_dependencies.dynamodb_client.check_and_set_idempotency.assert_called_once()
    assert result["s3"]["object"]["key"] == "new-file.txt"


def test_record_handler_duplicate_key(mock_dependencies):
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg2", "duplicate-file.txt", 1024)
    mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = False
    result = handler(record)
    assert result == {}


def test_record_handler_dynamodb_error_raises_transient_error(mock_dependencies):
    handler = make_record_handler(mock_dependencies)
    record = create_sqs_record("msg3", "any-file.txt", 1024)
    mock_dependencies.dynamodb_client.check_and_set_idempotency.side_effect = ClientError({}, "PutItem")
    with pytest.raises(TransientDynamoError):
        handler(record)


# --- Tests for _process_successful_batch ---

@patch("src.data_aggregator.app.process_and_stage_batch")
def test_process_successful_batch_happy_path(mock_core_processor, mock_lambda_context, mock_dependencies):
    s3_record = {"s3": {"object": {"key": "file.txt", "size": 5000}}}
    # This function expects a plain list of dictionaries, so we provide that directly.
    successful_records = [s3_record]
    _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)
    mock_core_processor.assert_called_once()
    call_args = mock_core_processor.call_args[1]
    assert call_args["records"] == [s3_record]


@patch("src.data_aggregator.app.process_and_stage_batch")
def test_process_successful_batch_raises_for_large_batch(mock_core_processor, mock_lambda_context, mock_dependencies):
    large_size = 101 * 1024 * 1024
    s3_record = {"s3": {"object": {"key": "large-file.txt", "size": large_size}}}
    successful_records = [s3_record]
    with pytest.raises(BatchTooLargeError):
        _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)
    mock_core_processor.assert_not_called()


# --- Tests for the main handler ---

@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.BatchProcessor")
def test_handler_full_success(mock_batch_processor, mock_process_batch, mock_lambda_context):
    """Tests the main handler for a batch where all records succeed."""
    # Arrange
    mock_processor_instance = mock_batch_processor.return_value

    # Simulate the state of the processor after it has run
    mock_processor_instance.success_messages = [
        create_mock_success_message("msg1", {"s3": {"object": {"key": "file1.txt"}}}),
        create_mock_success_message("msg2", {"s3": {"object": {"key": "file2.txt"}}}),
    ]
    mock_processor_instance.response.return_value = {"batchItemFailures": []}

    sqs_event = {"Records": [{}, {}]}  # Dummy content, as the processor is mocked

    # Act
    result = app.handler(sqs_event, mock_lambda_context)

    # Assert
    mock_process_batch.assert_called_once()
    called_with_records = mock_process_batch.call_args[0][0]
    assert len(called_with_records) == 2
    assert called_with_records[0]["s3"]["object"]["key"] == "file1.txt"
    assert result["batchItemFailures"] == []


@patch("src.data_aggregator.app._process_successful_batch")
@patch("src.data_aggregator.app.BatchProcessor")
def test_handler_batch_level_failure(mock_batch_processor, mock_process_batch, mock_lambda_context):
    """Tests that if batch processing fails, successful records are marked for retry."""
    # Arrange
    mock_processor_instance = mock_batch_processor.return_value

    # Simulate that two messages were initially successful
    mock_processor_instance.success_messages = [
        create_mock_success_message("msg1", {"s3": "..."}),
        create_mock_success_message("msg2", {"s3": "..."}),
    ]
    mock_processor_instance.response.return_value = {"batchItemFailures": []}

    # Make the next stage of processing fail
    mock_process_batch.side_effect = SQSBatchProcessingError("Retry the batch!")

    sqs_event = {"Records": [{}, {}]}

    # Act
    result = app.handler(sqs_event, mock_lambda_context)

    # Assert
    # All initially successful records should be in the final failure list
    assert len(result["batchItemFailures"]) == 2
    assert result["batchItemFailures"][0]["itemIdentifier"] == "msg1"
    assert result["batchItemFailures"][1]["itemIdentifier"] == "msg2"
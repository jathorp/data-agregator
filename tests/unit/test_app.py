"""
tests/unit/test_app.py

Comprehensive unit-tests for the refactored src.data_aggregator.app
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord

from src.data_aggregator import app
from src.data_aggregator.app import (
    SQSBatchProcessingError,
    _process_successful_batch,
    make_record_handler,
)

# ------------------------------------------------------------------ #
#                           FIXTURES                                 #
# ------------------------------------------------------------------ #

@pytest.fixture
def mock_dependencies(monkeypatch):
    """
    MODIFIED: A test fixture that prepares all dependencies for the handler,
    now simplified for the PULL model.
    """
    # Set environment variables for the new PULL model
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "test-idempotency")
    monkeypatch.setenv("ARCHIVE_BUCKET_NAME", "test-archive")
    monkeypatch.setenv("DISTRIBUTION_BUCKET_NAME", "test-distribution")

    # The only external dependency we need to mock now is the core processing logic
    with patch("src.data_aggregator.app.process_and_stage_batch") as mock_process:
        # Create a mock Dependencies object with the necessary clients
        deps = MagicMock()
        deps.s3_client = MagicMock()
        deps.dynamodb_client = MagicMock()
        deps.archive_bucket = "test-archive"
        deps.distribution_bucket = "test-distribution"

        # Attach the patched core logic function for asserting calls
        deps.mock_process_and_stage_batch = mock_process
        yield deps

@pytest.fixture
def mock_processor():
    """KEPT: Stub Powertools BatchProcessor so no internal logic runs."""
    with patch("src.data_aggregator.app.processor") as proc:
        yield proc

@pytest.fixture
def mock_lambda_context():
    """KEPT: Minimal Lambda context stub."""
    ctx = MagicMock(aws_request_id="test-req-id-123")
    return ctx

# ------------------------------------------------------------------ #
#                           HELPERS                                  #
# ------------------------------------------------------------------ #

def _create_sqs_record(obj_key: str, bucket: str = "unit-bucket") -> SQSRecord:
    """KEPT: Fabricate a Powertools SQSRecord with a wrapped S3 event."""
    s3_event = {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": obj_key}}}]}
    body = json.dumps(s3_event)
    return SQSRecord({"body": body, "messageId": f"msg-for-{obj_key}"})

# ------------------------------------------------------------------ #
#                LAYER 1 – make_record_handler()                     #
# ------------------------------------------------------------------ #

class TestRecordHandler:
    """KEPT: Unit-tests for per-record logic, which is unchanged."""

    def test_processes_new_key_successfully(self, mock_dependencies):
        mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = True
        handler = make_record_handler(mock_dependencies)
        record = _create_sqs_record("new.txt")
        result = handler(record)
        mock_dependencies.dynamodb_client.check_and_set_idempotency.assert_called_once()
        assert result["s3"]["object"]["key"] == "new.txt"

    def test_skips_duplicate_key(self, mock_dependencies):
        mock_dependencies.dynamodb_client.check_and_set_idempotency.return_value = False
        handler = make_record_handler(mock_dependencies)
        record = _create_sqs_record("dup.txt")
        result = handler(record)
        mock_dependencies.dynamodb_client.check_and_set_idempotency.assert_called_once()
        assert result == {}

# ------------------------------------------------------------------ #
#        LAYER 2 – handler() (stage-2 orchestration wrapper)         #
# ------------------------------------------------------------------ #

class TestHandlerBatchLogic:
    """KEPT: Focus on control-flow around _process_successful_batch."""

    @patch.object(app, "_process_successful_batch", autospec=True)
    def test_happy_path_calls_processing_function(
        self, mock_process_batch, mock_dependencies, mock_processor, mock_lambda_context
    ):
        s3_record = {"s3": {"object": {"key": "file.txt"}}}
        mock_processor.success_messages = [MagicMock(result=s3_record)]
        mock_processor.response.return_value = {"batchItemFailures": []}
        app.handler({"Records": []}, mock_lambda_context)
        mock_process_batch.assert_called_once()

    @patch.object(
        app,
        "_process_successful_batch",
        autospec=True,
        side_effect=SQSBatchProcessingError("Core processing failed"),
    )
    def test_when_processing_fails_returns_all_items(
        self, mock_process_batch, mock_dependencies, mock_processor, mock_lambda_context
    ):
        success1 = MagicMock(result={"s3": {}}, message_id="id-1")
        success2 = MagicMock(result={"s3": {}}, message_id="id-2")
        mock_processor.success_messages = [success1, success2]
        mock_processor.response.return_value = {"batchItemFailures": []}
        result = app.handler({"Records": []}, mock_lambda_context)
        assert result["batchItemFailures"] == [
            {"itemIdentifier": "id-1"},
            {"itemIdentifier": "id-2"},
        ]

# ------------------------------------------------------------------ #
#           LAYER 3 – _process_successful_batch() itself             #
# ------------------------------------------------------------------ #

class TestProcessSuccessfulBatch:
    """NEW: Rewritten tests for the simplified batch processing logic."""

    def test_happy_path_calls_core_logic_with_correct_args(
        self, mock_dependencies, mock_lambda_context
    ):
        """
        Verifies that the new function calls the core staging logic correctly.
        """
        # Arrange
        successful_records = [MagicMock(result={"s3": "record1"}), MagicMock(result={"s3": "record2"})]

        # Act
        _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)

        # Assert
        # Check that our core staging function was called once
        mock_dependencies.mock_process_and_stage_batch.assert_called_once()

        # Check that the arguments passed to it were correct
        call_args = mock_dependencies.mock_process_and_stage_batch.call_args
        assert call_args.kwargs["records"] == [{"s3": "record1"}, {"s3": "record2"}]
        assert call_args.kwargs["s3_client"] == mock_dependencies.s3_client
        assert call_args.kwargs["archive_bucket"] == "test-archive"
        assert call_args.kwargs["distribution_bucket"] == "test-distribution"
        assert call_args.kwargs["archive_key"] == "bundle-test-req-id-123.gz"

    def test_raises_sqs_batch_error_on_core_logic_failure(
        self, mock_dependencies, mock_lambda_context
    ):
        """
        Verifies the function raises SQSBatchProcessingError if the core logic fails.
        """
        # Arrange
        mock_dependencies.mock_process_and_stage_batch.side_effect = Exception("S3 Upload Failed")
        successful_records = [MagicMock(result={"s3": "record1"})]

        # Act & Assert
        with pytest.raises(SQSBatchProcessingError, match="Batch processing failed"):
            _process_successful_batch(successful_records, mock_lambda_context, mock_dependencies)
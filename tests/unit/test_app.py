"""
tests/unit/test_app.py

Comprehensive unit-tests for src.data_aggregator.app
----------------------------------------------------
 * zero real AWS / HTTP traffic
 * covers every branch we own
 * < 1 s runtime
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
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
def mock_dependencies():
    """Replace `Dependencies` with a loose mock we can freely shape."""
    with patch("src.data_aggregator.app.Dependencies") as mock_cls:
        deps = MagicMock()
        mock_cls.return_value = deps

        # hard-coded attrs used in production code
        deps.idempotency_ttl_seconds = 7 * 86_400
        deps.dynamodb_client = MagicMock()
        deps.circuit_breaker_client = MagicMock()
        deps.nifi_client = MagicMock()
        deps.metrics = MagicMock()

        yield deps


@pytest.fixture
def mock_processor():
    """Stub Powertools BatchProcessor so no internal logic runs."""
    with patch("src.data_aggregator.app.processor") as proc:
        yield proc


@pytest.fixture
def mock_lambda_context():
    """Minimal Lambda context stub."""
    ctx = MagicMock(aws_request_id="test-req-id")
    ctx.get_remaining_time_in_millis.return_value = 30_000
    return ctx


# ------------------------------------------------------------------ #
#                           HELPERS                                  #
# ------------------------------------------------------------------ #


def _create_sqs_record(obj_key: str, bucket: str = "unit-bucket") -> SQSRecord:
    """Fabricate a Powertools SQSRecord with a wrapped S3 event."""
    s3_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": obj_key},
                }
            }
        ]
    }
    body = json.dumps(s3_event)
    return SQSRecord({"body": body, "messageId": f"msg-for-{obj_key}"})


# ------------------------------------------------------------------ #
#                LAYER 1 – make_record_handler()                     #
# ------------------------------------------------------------------ #


class TestRecordHandler:
    """Unit-tests for per-record logic."""

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

    def test_raises_error_for_malformed_json(self, mock_dependencies):
        handler = make_record_handler(mock_dependencies)
        bad_record = SQSRecord({"body": "not json", "messageId": "bad-id"})

        with pytest.raises(ValueError, match="Malformed SQS message body"):
            handler(bad_record)


# ------------------------------------------------------------------ #
#        LAYER 2 – handler()  (stage-2 orchestration wrapper)        #
# ------------------------------------------------------------------ #


class TestHandlerBatchLogic:
    """Focus on control-flow around _process_successful_batch."""

    @patch.object(app, "_process_successful_batch", autospec=True, return_value=[])
    def test_happy_path_calls_processing_function(
        self,
        mock_process_batch,
        mock_dependencies,
        mock_processor,
        mock_lambda_context,
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
        side_effect=SQSBatchProcessingError("Circuit breaker open"),
    )
    def test_when_processing_fails_returns_all_items(
        self,
        mock_process_batch,
        mock_dependencies,
        mock_processor,
        mock_lambda_context,
    ):
        success1 = MagicMock(result={"s3": ...}, message_id="id-1")
        success2 = MagicMock(result={"s3": ...}, message_id="id-2")
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


@patch("src.data_aggregator.app.deliver_records")
class TestProcessSuccessfulBatch:
    """Fine-grained tests of the core delivery / CB logic."""

    def test_delivers_batch_when_circuit_closed(
        self,
        mock_deliver,
        mock_dependencies,
        mock_lambda_context,
    ):
        mock_dependencies.circuit_breaker_client.get_state.return_value = "CLOSED"
        good = MagicMock(result={"s3": ...})
        failures = _process_successful_batch([good], mock_lambda_context, mock_dependencies)

        mock_deliver.assert_called_once()
        mock_dependencies.circuit_breaker_client.record_success.assert_called_once()
        assert failures == []

    def test_raises_exception_when_circuit_open(
        self,
        mock_deliver,
        mock_dependencies,
        mock_lambda_context,
    ):
        mock_dependencies.circuit_breaker_client.get_state.return_value = "OPEN"
        with pytest.raises(SQSBatchProcessingError, match="Circuit Breaker is open"):
            _process_successful_batch([MagicMock(result={"s3": ...})],
                                      mock_lambda_context,
                                      mock_dependencies)
        mock_deliver.assert_not_called()

    def test_records_failure_and_bubbles_up_on_delivery_error(
        self,
        mock_deliver,
        mock_dependencies,
        mock_lambda_context,
    ):
        mock_dependencies.circuit_breaker_client.get_state.return_value = "CLOSED"
        mock_deliver.side_effect = requests.exceptions.ConnectionError("boom")

        with pytest.raises(SQSBatchProcessingError, match="Downstream connection error"):
            _process_successful_batch([MagicMock(result={"s3": ...})],
                                      mock_lambda_context,
                                      mock_dependencies)

        mock_deliver.assert_called_once()
        mock_dependencies.circuit_breaker_client.record_failure.assert_called_once()

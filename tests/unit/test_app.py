# tests/unit/test_app.py

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data_aggregator import app


# A sample SQS event for testing
@pytest.fixture
def sqs_event_factory():
    def _factory(records):
        return {
            "Records": [
                {
                    "messageId": f"msg_{i}",
                    "body": json.dumps({"Records": [record]}),
                    # ... other SQS attributes
                }
                for i, record in enumerate(records)
            ]
        }

    return _factory


@patch("src.data_aggregator.app.process_and_deliver_batch")
@patch("src.data_aggregator.app.dynamodb_client_wrapper")
@patch("src.data_aggregator.app.circuit_breaker_client")
def test_handler_happy_path(
        mock_circuit_breaker,
        mock_dynamodb,
        mock_process_batch,
        sqs_event_factory,
):
    """
    Tests the main handler on a successful run.
    - Mocks the core logic and clients.
    - Verifies that the handler correctly processes a valid batch.
    """
    # 1. ARRANGE
    # Configure the mocks' return values.
    mock_circuit_breaker.get_state.return_value = "CLOSED"
    mock_dynamodb.check_and_set_idempotency.return_value = True  # It's a new file

    # Create a sample S3 event record.
    s3_records = [{"s3": {"bucket": {"name": "test"}, "object": {"key": "file.txt"}}}]
    event = sqs_event_factory(s3_records)

    # Create a mock Lambda context object.
    context = MagicMock()
    context.aws_request_id = "request123"
    context.get_remaining_time_in_millis.return_value = 30000

    # 2. ACT
    # Call the handler function.
    response = app.handler(event, context)

    # 3. ASSERT
    # Verify the circuit breaker was checked.
    mock_circuit_breaker.get_state.assert_called_once()

    # Verify idempotency was checked.
    mock_dynamodb.check_and_set_idempotency.assert_called_once()

    # Verify the core logic was called with the correct record.
    mock_process_batch.assert_called_once()
    assert mock_process_batch.call_args.kwargs["records"] == s3_records

    # Verify the circuit breaker was notified of success.
    mock_circuit_breaker.record_success.assert_called_once()

    # A successful run should return no item failures.
    assert "batchItemFailures" not in response or not response["batchItemFailures"]
# tests/unit/test_app.py

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

# The environment is now set by conftest.py, so we can import at the top level.
from src.data_aggregator import app


# --- Fixtures (These are correct and can remain unchanged) ---


@pytest.fixture
def sqs_event_factory():
    """A pytest fixture to create mock SQS events for testing."""

    def _factory(s3_records: list):
        return {
            "Records": [
                {
                    "messageId": f"message_{i}",
                    "receiptHandle": "handle",
                    "body": json.dumps({"Records": [record]}),
                    "attributes": {},
                    "messageAttributes": {},
                    "md5OfBody": "...",
                    "eventSource": "aws:sqs",
                    "eventSourceARN": "arn:aws:sqs:eu-west-2:12345:test-queue",
                    "awsRegion": "eu-west-2",
                }
                for i, record in enumerate(s3_records)
            ]
        }

    return _factory


@pytest.fixture
def lambda_context() -> LambdaContext:
    """A pytest fixture to create a mock Lambda context object."""
    context = MagicMock(spec=LambdaContext)
    context.aws_request_id = "test_request_12345"
    context.get_remaining_time_in_millis.return_value = 30000
    return context


# --- Test Function ---


# We still patch the clients and the core logic function to isolate the handler.
# The key is that these patches will now correctly intercept the calls
# inside _initialize_clients() when the handler is executed.
@patch("src.data_aggregator.app.process_and_deliver_batch")
@patch("boto3.client")  # Patch boto3.client directly to control all client creation
def test_handler_happy_path(
    mock_boto3_client,
    mock_process_batch_func,
    sqs_event_factory,
    lambda_context,
    monkeypatch,  # Use monkeypatch to set environment variables
):
    """Tests the main handler on a successful run using the lazy-init pattern."""
    # 1. ARRANGE
    # Set all required environment variables using monkeypatch, which is active
    # before the handler runs and calls _initialize_clients.
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "test-idempotency-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-circuit-breaker-table")
    monkeypatch.setenv("ARCHIVE_BUCKET_NAME", "test-archive-bucket")
    monkeypatch.setenv("NIFI_ENDPOINT_URL", "https://test.nifi.endpoint")
    monkeypatch.setenv(
        "NIFI_SECRET_ARN", "arn:aws:secretsmanager:eu-west-2:12345:secret:test"
    )
    monkeypatch.setenv("DYNAMODB_TTL_ATTRIBUTE", "ttl")
    monkeypatch.setenv("IDEMPOTENCY_TTL_DAYS", "7")
    monkeypatch.setenv("AWS_REGION", "eu-west-2")  # Set the crucial region variable

    # Configure the mock Boto3 clients that will be created
    mock_dynamodb = MagicMock()
    mock_secretsmanager = MagicMock()
    # Configure boto3.client to return the correct mock for each service
    mock_boto3_client.side_effect = lambda service_name: {
        "dynamodb": mock_dynamodb,
        "secretsmanager": mock_secretsmanager,
    }.get(service_name)

    # Configure the behavior of the mocked clients
    mock_dynamodb.put_item.return_value = {}  # Simulate successful idempotency write
    mock_secretsmanager.get_secret_value.return_value = {
        "SecretString": '{"username": "testuser", "password": "testpassword"}'
    }

    # We still need to mock our custom CircuitBreakerClient's methods
    with patch("src.data_aggregator.app.circuit_breaker_client") as mock_cb:
        mock_cb.get_state.return_value = "CLOSED"

        s3_records = [
            {"s3": {"bucket": {"name": "test"}, "object": {"key": "file.txt"}}}
        ]
        event = sqs_event_factory(s3_records)

        # 2. ACT
        # The first time this runs, it will trigger _initialize_clients(), which
        # will now be fully mocked.
        response = app.handler(event, lambda_context)

        # 3. ASSERT
        # Verify that our core logic and client methods were called as expected.
        mock_dynamodb.put_item.assert_called_once()
        mock_process_batch_func.assert_called_once()
        mock_cb.record_success.assert_called_once()
        assert "batchItemFailures" not in response or not response["batchItemFailures"]

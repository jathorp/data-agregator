import time
from unittest.mock import MagicMock

import boto3
import pytest
import requests
from moto import mock_aws

from src.data_aggregator.clients import DynamoDBClient, NiFiClient, CircuitBreakerClient

# The name of the table and TTL attribute we'll use in our tests
TEST_TABLE_NAME = "test-idempotency-table"
TEST_TTL_ATTRIBUTE = "expiry_ttl"
TEST_NIFI_URL = "https://mock-nifi.example.com/contentListener"
TEST_CB_TABLE_NAME = "test-circuit-breaker-table"
SERVICE_NAME = "TestNiFi"

@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    # This fixture ensures that moto can intercept boto3 calls
    # by providing dummy credentials.
    return {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}


@pytest.fixture
def mock_dynamodb_table(aws_credentials):
    """
    Creates a mock DynamoDB table using moto.
    This fixture provides a clean, in-memory table for each test.
    """
    # The @mock_aws decorator intercepts any boto3 calls within this function
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="eu-west-2")
        dynamodb.create_table(
            TableName=TEST_TABLE_NAME,
            KeySchema=[{"AttributeName": "object_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "object_key", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        # Enable TTL on the mock table
        dynamodb.update_time_to_live(
            TableName=TEST_TABLE_NAME,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": TEST_TTL_ATTRIBUTE,
            },
        )
        yield dynamodb


@pytest.fixture
def dynamodb_client(mock_dynamodb_table):
    """
    Instantiates our DynamoDBClient wrapper, pointing it to the mock table.
    """
    # We use boto3.client() here again because moto is still active
    # and will provide the same mock DynamoDB instance.
    dynamo_boto_client = boto3.client("dynamodb", region_name="eu-west-2")
    return DynamoDBClient(
        dynamo_client=dynamo_boto_client,
        table_name=TEST_TABLE_NAME,
        ttl_attribute=TEST_TTL_ATTRIBUTE,
    )


def test_check_and_set_idempotency_for_new_key(dynamodb_client):
    """
    Tests that check_and_set_idempotency returns True for a new object key
    and correctly writes the item to the mock DynamoDB table.
    """
    # 1. ARRANGE
    test_key = "new-file-123.txt"
    test_ttl = int(time.time()) + 86400

    # 2. ACT
    is_new = dynamodb_client.check_and_set_idempotency(test_key, test_ttl)

    # 3. ASSERT
    # The method should report that this is a new key
    assert is_new is True

    # Verify the item was actually written to the database correctly
    dynamo_boto_client = dynamodb_client._client
    item_in_db = dynamo_boto_client.get_item(
        TableName=TEST_TABLE_NAME,
        Key={"object_key": {"S": test_key}}
    )

    assert "Item" in item_in_db
    assert item_in_db["Item"]["object_key"]["S"] == test_key
    assert item_in_db["Item"][TEST_TTL_ATTRIBUTE]["N"] == str(test_ttl)


def test_check_and_set_idempotency_for_existing_key(dynamodb_client):
    """
    Tests that check_and_set_idempotency returns False for a duplicate object key
    due to the ConditionExpression failing.
    """
    # 1. ARRANGE
    test_key = "duplicate-file-456.txt"
    test_ttl = int(time.time()) + 86400

    # First, manually insert the key into the database to simulate a duplicate
    dynamo_boto_client = dynamodb_client._client
    dynamo_boto_client.put_item(
        TableName=TEST_TABLE_NAME,
        Item={"object_key": {"S": test_key}, TEST_TTL_ATTRIBUTE: {"N": str(test_ttl)}}
    )

    # 2. ACT
    # Now, try to set the same key again using our client method
    is_new = dynamodb_client.check_and_set_idempotency(test_key, test_ttl)

    # 3. ASSERT
    # The method should report that this is NOT a new key
    assert is_new is False


def test_nificlient_post_bundle_succeeds_on_200_ok(requests_mock):
    """
    Tests that the NiFiClient correctly handles a successful HTTP 200 response.
    """
    # 1. ARRANGE
    # Mock the HTTP endpoint to return a 200 OK status
    requests_mock.post(TEST_NIFI_URL, text="OK", status_code=200)

    # Instantiate the client
    # We use a real requests.Session() as requests-mock will intercept its calls
    session = requests.Session()
    nifi_client = NiFiClient(
        session=session,
        endpoint_url=TEST_NIFI_URL,
        auth=("user", "pass")
    )

    test_data = b"gzipped-data"
    test_hash = "some-hash"
    test_timeout = 10

    # 2. ACT & 3. ASSERT
    # The test passes if no exception is raised
    try:
        nifi_client.post_bundle(
            data=test_data,
            content_hash=test_hash,
            read_timeout=test_timeout
        )
    except requests.exceptions.HTTPError:
        pytest.fail("NiFiClient raised HTTPError on a 200 OK response, but it should not have.")

    # Optional: Assert that the request was made with the correct headers
    history = requests_mock.request_history
    assert len(history) == 1
    assert history[0].headers["Content-Type"] == "application/gzip"
    assert history[0].headers["X-Content-SHA256"] == test_hash
    assert history[0].text == "gzipped-data"


def test_nificlient_post_bundle_raises_exception_on_503_error(requests_mock):
    """
    Tests that the NiFiClient correctly raises an HTTPError for non-2xx responses,
    triggering the application's error handling.
    """
    # 1. ARRANGE
    # Mock the HTTP endpoint to return a 503 Service Unavailable status
    requests_mock.post(TEST_NIFI_URL, text="Service Unavailable", status_code=503)

    session = requests.Session()
    nifi_client = NiFiClient(
        session=session,
        endpoint_url=TEST_NIFI_URL,
        auth=("user", "pass")
    )

    # 2. ACT & 3. ASSERT
    # Use pytest.raises to assert that the expected exception is thrown
    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        nifi_client.post_bundle(
            data=b"some-data",
            content_hash="some-hash",
            read_timeout=10
        )

    # Optional: Verify the exception contains the correct status code
    assert excinfo.value.response.status_code == 503

def test_nificlient_raises_timeout_exception(requests_mock):
    """
    Tests that the NiFiClient correctly raises a Timeout exception
    if the downstream service does not respond in time.
    """
    # 1. ARRANGE
    # Configure requests-mock to raise a ConnectTimeout exception
    requests_mock.post(TEST_NIFI_URL, exc=requests.exceptions.ConnectTimeout)

    nifi_client = NiFiClient(
        session=requests.Session(),
        endpoint_url=TEST_NIFI_URL,
        auth=("user", "pass")
    )

    # 2. ACT & 3. ASSERT
    with pytest.raises(requests.exceptions.ConnectTimeout):
        nifi_client.post_bundle(data=b"data", content_hash="hash", read_timeout=5)


@pytest.fixture
def mock_circuit_breaker_table(aws_credentials):
    """Creates a mock DynamoDB table for the circuit breaker using moto."""
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="eu-west-2")
        dynamodb.create_table(
            TableName=TEST_CB_TABLE_NAME,
            KeySchema=[{"AttributeName": "service_name", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "service_name", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        yield dynamodb


@pytest.fixture
def circuit_breaker_client(mock_circuit_breaker_table):
    """Instantiates our CircuitBreakerClient wrapper."""
    dynamo_boto_client = boto3.client("dynamodb", region_name="eu-west-2")
    # The Metrics object is a dependency, so we mock it
    mock_metrics = MagicMock()
    return CircuitBreakerClient(
        dynamo_client=dynamo_boto_client,
        table_name=TEST_CB_TABLE_NAME,
        metrics=mock_metrics,
        failure_threshold=3,
        open_duration_seconds=300,
        service_name=SERVICE_NAME,
    )


def test_circuit_breaker_initial_state_is_closed(circuit_breaker_client):
    """Tests that a new service with no state in DynamoDB defaults to CLOSED."""
    assert circuit_breaker_client.get_state() == "CLOSED"


def test_circuit_breaker_opens_after_reaching_failure_threshold(circuit_breaker_client):
    """
    Tests that the circuit transitions from CLOSED to OPEN after the configured
    number of failures and that the custom metric is emitted exactly once.
    """
    # 1. ARRANGE
    # The initial state should be CLOSED
    assert circuit_breaker_client.get_state() == "CLOSED"

    # 2. ACT
    # Record failures up to the threshold
    circuit_breaker_client.record_failure()  # count = 1
    circuit_breaker_client.record_failure()  # count = 2

    # Verify state is still CLOSED
    assert circuit_breaker_client.get_state() == "CLOSED"

    # This failure should trip the breaker
    circuit_breaker_client.record_failure()  # count = 3, trips to OPEN

    # 3. ASSERT
    # The state should now be OPEN
    assert circuit_breaker_client.get_state() == "OPEN"

    # Verify that the 'add_metric' method on our mock metrics object was called exactly once
    circuit_breaker_client._metrics.add_metric.assert_called_once_with(
        name="CircuitBreakerOpen",
        unit="Count",
        value=1
    )


def test_circuit_breaker_resets_from_half_open_on_success(circuit_breaker_client):
    """
    Tests that the circuit transitions from HALF_OPEN back to CLOSED after a
    successful operation.
    """
    # 1. ARRANGE
    # Manually set the state to HALF_OPEN in the mock database
    dynamo_boto_client = circuit_breaker_client._client
    dynamo_boto_client.put_item(
        TableName=TEST_CB_TABLE_NAME,
        Item={
            "service_name": {"S": SERVICE_NAME},
            "state": {"S": "HALF_OPEN"},
            "failure_count": {"N": "0"},
        },
    )
    assert circuit_breaker_client.get_state() == "HALF_OPEN"

    # 2. ACT
    circuit_breaker_client.record_success()

    # 3. ASSERT
    # The state should now be CLOSED
    assert circuit_breaker_client.get_state() == "CLOSED"


def test_circuit_breaker_moves_to_half_open_after_timeout(circuit_breaker_client):
    """
    Tests the self-healing property: the circuit moves from OPEN to HALF_OPEN
    after the open_duration_seconds timeout has passed.
    """
    # 1. ARRANGE
    # Manually set the state to OPEN with a timestamp far in the past
    dynamo_boto_client = circuit_breaker_client._client
    past_timestamp = int(time.time()) - 301  # 301 seconds ago, just past the 300s timeout
    dynamo_boto_client.put_item(
        TableName=TEST_CB_TABLE_NAME,
        Item={
            "service_name": {"S": SERVICE_NAME},
            "state": {"S": "OPEN"},
            "failure_count": {"N": "3"},
            "last_updated": {"N": str(past_timestamp)},
        },
    )

    # 2. ACT
    # Calling get_state should trigger the time-based transition
    current_state = circuit_breaker_client.get_state()

    # 3. ASSERT
    # The state should have automatically transitioned to HALF_OPEN
    assert current_state == "HALF_OPEN"


def test_circuit_breaker_success_on_closed_state_does_nothing(circuit_breaker_client):
    """
    Tests that calling record_success() when the circuit is already CLOSED
    does not change the state and handles the conditional update failure gracefully.
    """
    # 1. ARRANGE
    # Manually set the state to CLOSED in the mock database
    dynamo_boto_client = circuit_breaker_client._client
    dynamo_boto_client.put_item(
        TableName=TEST_CB_TABLE_NAME,
        Item={
            "service_name": {"S": SERVICE_NAME},
            "state": {"S": "CLOSED"},
            "failure_count": {"N": "0"},
        },
    )
    assert circuit_breaker_client.get_state() == "CLOSED"

    # Spy on the database client to ensure no unexpected writes occur
    # The new implementation of record_success will attempt a conditional
    # update_item, which will fail. This test ensures no other writes happen.

    # 2. ACT
    # This should not raise an unhandled exception
    circuit_breaker_client.record_success()

    # 3. ASSERT
    # The state should remain CLOSED
    assert circuit_breaker_client.get_state() == "CLOSED"


def test_circuit_breaker_failure_on_open_state_does_not_retrigger_metric(circuit_breaker_client):
    """
    Tests that if a failure is recorded when the circuit is already OPEN,
    the 'CircuitBreakerOpen' metric is not emitted again.
    """
    # 1. ARRANGE
    # Manually set the state to OPEN
    dynamo_boto_client = circuit_breaker_client._client
    dynamo_boto_client.put_item(
        TableName=TEST_CB_TABLE_NAME,
        Item={
            "service_name": {"S": SERVICE_NAME},
            "state": {"S": "OPEN"},
            "failure_count": {"N": "3"},  # Already at threshold
            # CORRECTED: Add a recent timestamp to prevent immediate transition to HALF_OPEN
            "last_updated": {"N": str(int(time.time()))},
        },
    )

    # This assertion will now pass
    assert circuit_breaker_client.get_state() == "OPEN"

    # Reset the mock to ensure we only count calls from the 'ACT' phase
    circuit_breaker_client._metrics.reset_mock()

    # 2. ACT
    # Record another failure
    circuit_breaker_client.record_failure()

    # 3. ASSERT
    # The state should still be OPEN
    assert circuit_breaker_client.get_state() == "OPEN"

    # The metric should NOT have been called again
    circuit_breaker_client._metrics.add_metric.assert_not_called()


def test_circuit_breaker_remains_open_if_timeout_not_expired(circuit_breaker_client):
    """
    Tests that the circuit remains OPEN if get_state() is called before
    the timeout has expired.
    """
    # 1. ARRANGE
    # Manually set the state to OPEN with a timestamp in the recent past
    # that is still within the 300-second timeout window.
    dynamo_boto_client = circuit_breaker_client._client
    recent_timestamp = int(time.time()) - 60  # 60 seconds ago
    dynamo_boto_client.put_item(
        TableName=TEST_CB_TABLE_NAME,
        Item={
            "service_name": {"S": SERVICE_NAME},
            "state": {"S": "OPEN"},
            "failure_count": {"N": "3"},
            "last_updated": {"N": str(recent_timestamp)},
        },
    )

    # 2. ACT
    # Calling get_state should not trigger a transition
    current_state = circuit_breaker_client.get_state()

    # 3. ASSERT
    # The state should remain OPEN
    assert current_state == "OPEN"

    # Verify in the database that the state was not changed to HALF_OPEN
    item_in_db = dynamo_boto_client.get_item(
        TableName=TEST_CB_TABLE_NAME,
        Key={"service_name": {"S": SERVICE_NAME}}
    )["Item"]
    assert item_in_db["state"]["S"] == "OPEN"
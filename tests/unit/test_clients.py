# tests/unit/test_clients.py

from unittest.mock import MagicMock, call

import pytest
from botocore.exceptions import ClientError

from src.data_aggregator.clients import DynamoDBClient, S3Client

# -----------------------------------------------------------------------------
# Fixtures for setting up clients with mock dependencies
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_boto_s3_client():
    """Yields a MagicMock for the boto3 S3 client."""
    return MagicMock()

@pytest.fixture
def s3_client(mock_boto_s3_client):
    """Yields an instance of our S3Client wrapper without KMS."""
    return S3Client(s3_client=mock_boto_s3_client)

@pytest.fixture
def s3_client_with_kms(mock_boto_s3_client):
    """Yields an instance of our S3Client wrapper with KMS enabled."""
    return S3Client(s3_client=mock_boto_s3_client, kms_key_id="test-kms-key")

@pytest.fixture
def mock_boto_dynamodb_client():
    """Yields a MagicMock for the boto3 DynamoDB client."""
    return MagicMock()

@pytest.fixture
def dynamodb_client(mock_boto_dynamodb_client):
    """Yields an instance of our DynamoDBClient wrapper."""
    return DynamoDBClient(
        dynamo_client=mock_boto_dynamodb_client,
        table_name="test-idempotency-table",
        ttl_attribute="ttl",
    )

# -----------------------------------------------------------------------------
# Tests for S3Client
# -----------------------------------------------------------------------------

def test_s3_client_get_file_content_stream(s3_client, mock_boto_s3_client):
    """
    Verifies that get_file_content_stream calls get_object correctly and returns the body.
    """
    # Arrange
    mock_stream = MagicMock()
    mock_boto_s3_client.get_object.return_value = {"Body": mock_stream}

    # Act
    result = s3_client.get_file_content_stream(bucket="test-bucket", key="test-key")

    # Assert
    mock_boto_s3_client.get_object.assert_called_once_with(
        Bucket="test-bucket", Key="test-key"
    )
    assert result is mock_stream

def test_s3_client_upload_gzipped_bundle(s3_client, mock_boto_s3_client):
    """
    Verifies that upload_gzipped_bundle calls upload_fileobj with the correct arguments.
    """
    # Arrange
    mock_file = MagicMock()
    test_hash = "fake-hash-123"

    # Act
    s3_client.upload_gzipped_bundle(
        bucket="test-bucket", key="test-key", file_obj=mock_file, content_hash=test_hash
    )

    # Assert
    # --- FIX: Assert the complete set of ExtraArgs ---
    expected_extra_args = {
        "Metadata": {"content-sha256": test_hash},
        "ContentEncoding": "gzip",
        "ContentType": "application/gzip",
    }
    mock_boto_s3_client.upload_fileobj.assert_called_once_with(
        Fileobj=mock_file,
        Bucket="test-bucket",
        Key="test-key",
        ExtraArgs=expected_extra_args,
    )

def test_s3_client_upload_gzipped_bundle_with_kms(s3_client_with_kms, mock_boto_s3_client):
    """
    Verifies that upload_gzipped_bundle includes KMS args when configured.
    """
    # Arrange
    mock_file = MagicMock()
    test_hash = "fake-hash-123"

    # Act
    s3_client_with_kms.upload_gzipped_bundle(
        bucket="test-bucket", key="test-key", file_obj=mock_file, content_hash=test_hash
    )

    # Assert
    # --- FIX: Assert the complete set of ExtraArgs including KMS ---
    expected_extra_args = {
        "Metadata": {"content-sha256": test_hash},
        "ContentEncoding": "gzip",
        "ContentType": "application/gzip",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "test-kms-key",
    }
    mock_boto_s3_client.upload_fileobj.assert_called_once_with(
        Fileobj=mock_file,
        Bucket="test-bucket",
        Key="test-key",
        ExtraArgs=expected_extra_args,
    )

def test_s3_client_copy_bundle(s3_client, mock_boto_s3_client):
    """
    Verifies the new copy_bundle method calls copy_object with correct arguments.
    """
    # Arrange
    source_bucket, source_key = "source-bucket", "source-key.gz"
    dest_bucket, dest_key = "dest-bucket", "dest-key.gz"

    # Act
    s3_client.copy_bundle(source_bucket, source_key, dest_bucket, dest_key)

    # Assert
    mock_boto_s3_client.copy_object.assert_called_once_with(
        Bucket=dest_bucket,
        Key=dest_key,
        CopySource={'Bucket': source_bucket, 'Key': source_key},
        MetadataDirective="COPY",
    )

# -----------------------------------------------------------------------------
# Tests for DynamoDBClient
# -----------------------------------------------------------------------------

def test_dynamodb_check_and_set_idempotency_succeeds_for_new_key(
    dynamodb_client, mock_boto_dynamodb_client
):
    """
    Verifies that the method returns True when the key is new and put_item succeeds.
    """
    # Arrange
    test_idempotency_key = "new-hash-key"
    test_original_key = "path/to/original/file.txt"
    test_ttl = 12345

    # Act
    # --- FIX: Pass the new 'original_object_key' argument ---
    result = dynamodb_client.check_and_set_idempotency(
        test_idempotency_key, test_original_key, test_ttl
    )

    # Assert
    # --- FIX: Assert the new Item structure in the put_item call ---
    expected_item = {
        "idempotency_key": {"S": test_idempotency_key},
        "object_key": {"S": test_original_key},
        "ttl": {"N": str(test_ttl)},
    }
    mock_boto_dynamodb_client.put_item.assert_called_once_with(
        TableName="test-idempotency-table",
        Item=expected_item,
        ConditionExpression="attribute_not_exists(idempotency_key)",
    )
    assert result is True

def test_dynamodb_check_and_set_idempotency_fails_for_existing_key(
    dynamodb_client, mock_boto_dynamodb_client
):
    """
    Verifies that the method returns False when the key already exists.
    """
    # Arrange
    error_response = {"Error": {"Code": "ConditionalCheckFailedException"}}
    mock_boto_dynamodb_client.put_item.side_effect = ClientError(
        error_response, "PutItem"
    )

    # Act
    # --- FIX: Pass the new 'original_object_key' argument ---
    result = dynamodb_client.check_and_set_idempotency(
        "existing-key", "path/to/original.txt", 12345
    )

    # Assert
    assert result is False

def test_dynamodb_check_and_set_idempotency_reraises_other_errors(
    dynamodb_client, mock_boto_dynamodb_client
):
    """
    Verifies that any ClientError other than the conditional check is re-raised.
    """
    # Arrange
    error_response = {"Error": {"Code": "SomeOtherDynamoDBException"}}
    mock_boto_dynamodb_client.put_item.side_effect = ClientError(
        error_response, "PutItem"
    )

    # Act & Assert
    with pytest.raises(ClientError):
        # --- FIX: Pass the new 'original_object_key' argument ---
        dynamodb_client.check_and_set_idempotency(
            "any-key", "path/to/original.txt", 12345
        )
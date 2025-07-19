# tests/unit/test_clients.py

"""
Unit tests for the S3Client wrapper in src/data_aggregator/clients.py.

These tests ensure that our custom S3Client correctly interacts with the
underlying boto3 client, passing the expected arguments for various
operations like getting objects and uploading files with and without KMS.
"""

from unittest.mock import MagicMock

import pytest

from src.data_aggregator.clients import S3Client


# -----------------------------------------------------------------------------
# Fixtures for setting up clients with mock dependencies
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_boto_s3_client() -> MagicMock:
    """Yields a MagicMock for the boto3 S3 client."""
    return MagicMock()


@pytest.fixture
def s3_client(mock_boto_s3_client: MagicMock) -> S3Client:
    """Yields an instance of our S3Client wrapper without KMS."""
    return S3Client(s3_client=mock_boto_s3_client)


@pytest.fixture
def s3_client_with_kms(mock_boto_s3_client: MagicMock) -> S3Client:
    """Yields an instance of our S3Client wrapper with KMS enabled."""
    return S3Client(s3_client=mock_boto_s3_client, kms_key_id="test-kms-key")


# -----------------------------------------------------------------------------
# Tests for S3Client
# -----------------------------------------------------------------------------


def test_s3_client_get_file_content_stream(
    s3_client: S3Client, mock_boto_s3_client: MagicMock
):
    """
    Verifies that get_file_content_stream calls get_object correctly and returns the body.
    """
    # Arrange
    mock_stream = MagicMock()
    mock_boto_s3_client.get_object.return_value = {"Body": mock_stream}
    bucket, key = "test-bucket", "test-key"

    # Act
    result = s3_client.get_file_content_stream(bucket=bucket, key=key)

    # Assert
    mock_boto_s3_client.get_object.assert_called_once_with(Bucket=bucket, Key=key)
    assert result is mock_stream


def test_s3_client_upload_gzipped_bundle(
    s3_client: S3Client, mock_boto_s3_client: MagicMock
):
    """
    Verifies that upload_gzipped_bundle calls upload_fileobj with the correct arguments
    when no KMS key is configured.
    """
    # Arrange
    mock_file = MagicMock()
    test_hash = "fake-hash-123"
    expected_extra_args = {
        "Metadata": {"content-sha256": test_hash},
        "ContentEncoding": "gzip",
        "ContentType": "application/gzip",
    }

    # Act
    s3_client.upload_gzipped_bundle(
        bucket="test-bucket", key="test-key", file_obj=mock_file, content_hash=test_hash
    )

    # Assert
    mock_boto_s3_client.upload_fileobj.assert_called_once_with(
        Fileobj=mock_file,
        Bucket="test-bucket",
        Key="test-key",
        ExtraArgs=expected_extra_args,
    )


def test_s3_client_upload_gzipped_bundle_with_kms(
    s3_client_with_kms: S3Client, mock_boto_s3_client: MagicMock
):
    """
    Verifies that upload_gzipped_bundle includes KMS arguments in ExtraArgs
    when a KMS key is configured.
    """
    # Arrange
    mock_file = MagicMock()
    test_hash = "fake-hash-123"
    expected_extra_args = {
        "Metadata": {"content-sha256": test_hash},
        "ContentEncoding": "gzip",
        "ContentType": "application/gzip",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "test-kms-key",
    }

    # Act
    s3_client_with_kms.upload_gzipped_bundle(
        bucket="test-bucket", key="test-key", file_obj=mock_file, content_hash=test_hash
    )

    # Assert
    mock_boto_s3_client.upload_fileobj.assert_called_once_with(
        Fileobj=mock_file,
        Bucket="test-bucket",
        Key="test-key",
        ExtraArgs=expected_extra_args,
    )

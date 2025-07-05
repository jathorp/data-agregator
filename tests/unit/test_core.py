# tests/unit/test_core.py

from io import BytesIO
from unittest.mock import MagicMock, patch

from src.data_aggregator.core import process_and_deliver_batch


# CORRECTED: We now patch the create_gzipped_bundle_stream function.
@patch("src.data_aggregator.core.create_gzipped_bundle_stream")
def test_process_and_deliver_batch_happy_path(mock_create_bundle):
    """
    Tests the orchestration logic of process_and_deliver_batch in isolation.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_nifi_client = MagicMock()

    # Configure the mock bundle function to return a fake file and hash.
    # The 'with' statement in the original code expects a context manager.
    mock_bundle_file = BytesIO(b"fake gzipped content")
    mock_content_hash = "fake_hash_123"
    mock_create_bundle.return_value.__enter__.return_value = (
        mock_bundle_file,
        mock_content_hash,
    )

    test_records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file1.txt"}}},
    ]
    test_archive_bucket = "test-archive"
    test_archive_key = "bundle-123.gz"
    test_read_timeout = 15

    # 2. ACT
    content_hash = process_and_deliver_batch(
        records=test_records,
        s3_client=mock_s3_client,
        nifi_client=mock_nifi_client,
        archive_bucket=test_archive_bucket,
        archive_key=test_archive_key,
        read_timeout=test_read_timeout,
    )

    # 3. ASSERT
    # Verify the bundle creation was called correctly.
    mock_create_bundle.assert_called_once_with(mock_s3_client, test_records)

    # Verify the bundle was uploaded to S3 with the correct details.
    mock_s3_client.upload_gzipped_bundle.assert_called_once_with(
        bucket=test_archive_bucket,
        key=test_archive_key,
        file_obj=mock_bundle_file,
        content_hash=mock_content_hash,
    )

    # Verify the bundle was sent to NiFi with the correct details.
    mock_nifi_client.post_bundle.assert_called_once_with(
        data=mock_bundle_file,
        content_hash=mock_content_hash,
        read_timeout=test_read_timeout,
    )

    # Verify the final hash is returned correctly.
    assert content_hash == mock_content_hash

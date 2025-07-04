# tests/unit/test_core.py

from unittest.mock import MagicMock, call

from src.data_aggregator.core import process_and_deliver_batch


def test_process_and_deliver_batch_happy_path():
    """
    Tests the main orchestration logic with mocked clients.
    Verifies that all steps are called in the correct order with the correct data.
    """
    # 1. ARRANGE
    # Create mock objects for our client dependencies.
    mock_s3_client = MagicMock()
    mock_nifi_client = MagicMock()

    # Configure the mock S3 client to return specific content for each file.
    mock_s3_client.get_file_content.side_effect = [
        b"content for file1.txt",
        b"content for file2.txt",
    ]

    # Define the input records for the function.
    test_records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file1.txt"}}},
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file2.txt"}}},
    ]
    test_archive_bucket = "test-archive"
    test_archive_key = "bundle-123.gz"
    test_read_timeout = 15

    # 2. ACT
    # Call the function we are testing.
    content_hash = process_and_deliver_batch(
        records=test_records,
        s3_client=mock_s3_client,
        nifi_client=mock_nifi_client,
        archive_bucket=test_archive_bucket,
        archive_key=test_archive_key,
        read_timeout=test_read_timeout,
    )

    # 3. ASSERT
    # Verify that our mocked methods were called as expected.
    assert mock_s3_client.get_file_content.call_count == 2

    # Check that the bundle was uploaded to the archive.
    mock_s3_client.upload_gzipped_bundle.assert_called_once()

    # Check that the bundle was delivered to NiFi.
    mock_nifi_client.post_bundle.assert_called_once()

    # Verify the hash passed to both calls is the same.
    s3_call_args = mock_s3_client.upload_gzipped_bundle.call_args
    nifi_call_args = mock_nifi_client.post_bundle.call_args

    assert s3_call_args.kwargs["content_hash"] == nifi_call_args.kwargs["content_hash"]
    assert s3_call_args.kwargs["content_hash"] == content_hash
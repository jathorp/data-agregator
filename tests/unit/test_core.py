# tests/unit/test_core.py

import gzip
import hashlib
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from src.data_aggregator.core import process_and_deliver_batch, create_gzipped_bundle_stream


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

def test_create_gzipped_bundle_stream_creates_valid_bundle():
    """
    Tests that the create_gzipped_bundle_stream function correctly:
    1. Creates a valid Gzip stream.
    2. Includes all file content with headers/footers.
    3. Calculates the correct SHA-256 hash of the uncompressed content.
    """
    # 1. ARRANGE
    # Mock the S3 client and its streaming response
    mock_s3_client = MagicMock()
    file1_content = b"This is the first file."
    file2_content = b"This is the second file."

    # --- UPDATED: Create more realistic stream mocks ---
    # Instead of BytesIO, we use MagicMock and configure the iter_chunks method.
    mock_stream1 = MagicMock()
    # .iter_chunks() returns a generator. For a test, returning a list is a simple
    # and effective way to mock this iterable behavior.
    mock_stream1.iter_chunks.return_value = [file1_content]

    mock_stream2 = MagicMock()
    mock_stream2.iter_chunks.return_value = [file2_content]

    # The S3 client's method will now return our more realistic mocks in order.
    mock_s3_client.get_file_content_stream.return_value.__enter__.side_effect = [
        mock_stream1,
        mock_stream2,
    ]

    records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file1.txt"}}},
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file2.txt"}}},
    ]

    # Calculate the expected hash manually (this logic remains the same)
    expected_hasher = hashlib.sha256()
    expected_hasher.update(b"--- BEGIN file1.txt ---\n")
    expected_hasher.update(file1_content)
    expected_hasher.update(b"\n--- END file1.txt ---\n")
    expected_hasher.update(b"--- BEGIN file2.txt ---\n")
    expected_hasher.update(file2_content)
    expected_hasher.update(b"\n--- END file2.txt ---\n")
    expected_hash = expected_hasher.hexdigest()

    # 2. ACT
    with create_gzipped_bundle_stream(mock_s3_client, records) as (bundle_file, content_hash):
        bundle_content = bundle_file.read()

    # 3. ASSERT
    decompressed_content = gzip.decompress(bundle_content)

    assert content_hash == expected_hash
    assert b"--- BEGIN file1.txt ---" in decompressed_content
    assert file1_content in decompressed_content
    assert b"--- END file1.txt ---" in decompressed_content
    assert b"--- BEGIN file2.txt ---" in decompressed_content
    assert file2_content in decompressed_content
    assert b"--- END file2.txt ---" in decompressed_content


def test_process_and_deliver_batch_raises_error_for_empty_records():
    """
    Verifies that the function raises a ValueError if called with an empty list of records.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_nifi_client = MagicMock()

    # 2. ACT & ASSERT
    with pytest.raises(ValueError, match="Cannot process an empty batch of records."):
        process_and_deliver_batch(
            records=[],  # Empty list of records
            s3_client=mock_s3_client,
            nifi_client=mock_nifi_client,
            archive_bucket="any-bucket",
            archive_key="any-key",
            read_timeout=10,
        )

def test_create_gzipped_bundle_stream_handles_empty_file():
    """
    Verifies the bundler correctly handles a 0-byte file from S3.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()

    # Mock a stream that yields no chunks, simulating an empty file
    mock_empty_stream = MagicMock()
    mock_empty_stream.iter_chunks.return_value = []  # No content
    mock_s3_client.get_file_content_stream.return_value.__enter__.return_value = mock_empty_stream

    records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "empty.txt"}}},
    ]

    # Calculate the hash of just the header and footer
    expected_hasher = hashlib.sha256()
    expected_hasher.update(b"--- BEGIN empty.txt ---\n")
    # No content is updated here
    expected_hasher.update(b"\n--- END empty.txt ---\n")
    expected_hash = expected_hasher.hexdigest()

    # 2. ACT
    with create_gzipped_bundle_stream(mock_s3_client, records) as (bundle_file, content_hash):
        decompressed_content = gzip.decompress(bundle_file.read())

    # 3. ASSERT
    assert content_hash == expected_hash
    assert decompressed_content == b"--- BEGIN empty.txt ---\n\n--- END empty.txt ---\n"

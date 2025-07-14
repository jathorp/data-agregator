# tests/unit/test_core.py

import gzip
import hashlib
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.data_aggregator.core import create_gzipped_bundle_stream, process_and_stage_batch


# --- FIX: Add a reusable fixture for the mock Lambda context ---
@pytest.fixture
def mock_lambda_context() -> MagicMock:
    """Provides a mock LambdaContext object for tests."""
    context = MagicMock(spec=LambdaContext)
    # Ensure the timeout check always passes by returning a large number of milliseconds
    context.get_remaining_time_in_millis.return_value = 300_000
    return context


@patch("src.data_aggregator.core.create_gzipped_bundle_stream")
def test_process_and_stage_batch_happy_path(mock_create_bundle, mock_lambda_context):
    """
    Tests the orchestration logic of process_and_stage_batch, verifying the
    new 'upload then copy' pattern.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_bundle_file = MagicMock(spec=BytesIO)
    mock_content_hash = "fake_hash_123"
    mock_create_bundle.return_value.__enter__.return_value = (
        mock_bundle_file,
        mock_content_hash,
    )

    test_records = [{"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file1.txt"}}}]
    test_archive_bucket = "test-archive"
    test_distribution_bucket = "test-distribution"
    test_archive_key = "bundle-123.gz"

    # 2. ACT
    # --- FIX: Pass the required mock_lambda_context ---
    content_hash = process_and_stage_batch(
        records=test_records,
        s3_client=mock_s3_client,
        archive_bucket=test_archive_bucket,
        distribution_bucket=test_distribution_bucket,
        archive_key=test_archive_key,
        context=mock_lambda_context,
    )

    # 3. ASSERT
    # --- FIX: Update assertions to match the new 'upload then copy' logic ---
    mock_create_bundle.assert_called_once_with(mock_s3_client, test_records, context=mock_lambda_context)

    # Assert the initial upload to the archive bucket
    mock_s3_client.upload_gzipped_bundle.assert_called_once_with(
        bucket=test_archive_bucket, key=test_archive_key, file_obj=mock_bundle_file, content_hash=mock_content_hash
    )

    # Assert the S3 copy operation to the distribution bucket
    mock_s3_client.copy_bundle.assert_called_once_with(
        source_bucket=test_archive_bucket, source_key=test_archive_key,
        dest_bucket=test_distribution_bucket, dest_key=test_archive_key
    )

    # The file.seek() is now an implementation detail of the (mocked) create_bundle
    # function, so we no longer assert it here.

    assert content_hash == mock_content_hash

def test_create_gzipped_bundle_stream_creates_valid_bundle(mock_lambda_context):
    """
    Tests that the create_gzipped_bundle_stream function correctly:
    1. Creates a valid Gzip stream.
    2. Includes all file content with headers/footers.
    3. Calculates the correct SHA-256 hash of the uncompressed content.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    file1_content = b"This is the first file."
    file2_content = b"This is the second file."

    mock_stream1 = MagicMock()
    mock_stream1.iter_chunks.return_value = [file1_content]
    mock_stream2 = MagicMock()
    mock_stream2.iter_chunks.return_value = [file2_content]

    # --- FIX: Set the side_effect on the method call itself, not on __enter__ ---
    mock_s3_client.get_file_content_stream.side_effect = [
        mock_stream1,
        mock_stream2,
    ]

    records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file1.txt"}}},
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "file2.txt"}}},
    ]

    # The original manual hash calculation was correct.
    expected_hasher = hashlib.sha256()
    expected_hasher.update(b"--- BEGIN file1.txt ---\n")
    expected_hasher.update(file1_content)
    expected_hasher.update(b"\n--- END file1.txt ---\n")
    expected_hasher.update(b"--- BEGIN file2.txt ---\n")
    expected_hasher.update(file2_content)
    expected_hasher.update(b"\n--- END file2.txt ---\n")
    expected_hash = expected_hasher.hexdigest()

    # 2. ACT
    with create_gzipped_bundle_stream(mock_s3_client, records, mock_lambda_context) as (bundle_file, content_hash):
        bundle_content = bundle_file.read()

    # 3. ASSERT
    decompressed_content = gzip.decompress(bundle_content)

    # 3a. Content and hash must exactly match our hand-rolled expectation
    expected_content = (
        b"--- BEGIN file1.txt ---\n"
        b"This is the first file."
        b"\n--- END file1.txt ---\n"
        b"--- BEGIN file2.txt ---\n"
        b"This is the second file."
        b"\n--- END file2.txt ---\n"
    )
    assert decompressed_content == expected_content
    assert content_hash == expected_hash

    # 3b. The S3 client should have been asked for each object once and only once, in order
    assert mock_s3_client.get_file_content_stream.call_count == 2
    mock_s3_client.get_file_content_stream.assert_has_calls(
        [
            (("test-bucket", "file1.txt"),),  # positional-only args
            (("test-bucket", "file2.txt"),),
        ]
    )



def test_process_and_stage_batch_raises_error_for_empty_records(mock_lambda_context):
    """
    Verifies that the function raises a ValueError if called with an empty list of records.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()

    # 2. ACT & ASSERT
    with pytest.raises(ValueError, match="Cannot process an empty batch."):
        # --- FIX: Pass the required mock_lambda_context ---
        process_and_stage_batch(
            records=[],
            s3_client=mock_s3_client,
            archive_bucket="any-bucket",
            distribution_bucket="any-distribution-bucket",
            archive_key="any-key",
            context=mock_lambda_context,
        )

def test_create_gzipped_bundle_stream_handles_empty_file(mock_lambda_context):
    """
    Verifies the bundler correctly handles a 0-byte file from S3.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_empty_stream = MagicMock()
    mock_empty_stream.iter_chunks.return_value = []
    mock_s3_client.get_file_content_stream.return_value.__enter__.return_value = mock_empty_stream

    records = [
        {"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "empty.txt"}}},
    ]

    expected_hasher = hashlib.sha256()
    expected_hasher.update(b"--- BEGIN empty.txt ---\n")
    expected_hasher.update(b"\n--- END empty.txt ---\n")
    expected_hash = expected_hasher.hexdigest()

    # 2. ACT
    # --- FIX: Pass the required mock_lambda_context ---
    with create_gzipped_bundle_stream(mock_s3_client, records, mock_lambda_context) as (bundle_file, content_hash):
        decompressed_content = gzip.decompress(bundle_file.read())

    # 3. ASSERT
    assert content_hash == expected_hash
    assert decompressed_content == b"--- BEGIN empty.txt ---\n\n--- END empty.txt ---\n"
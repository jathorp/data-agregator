# tests/unit/test_core.py

import hashlib
import io
import os
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.data_aggregator.core import (
    create_tar_gz_bundle_stream,
    process_and_stage_batch,
    _sanitize_s3_key,
    _buffer_and_validate,
)
from src.data_aggregator.exceptions import BundlingTimeoutError


@pytest.fixture
def mock_lambda_context() -> MagicMock:
    """Provides a mock LambdaContext object that passes timeout checks."""
    context = MagicMock(spec=LambdaContext)
    context.get_remaining_time_in_millis.return_value = 300_000
    return context


# --- High-Level Orchestration Tests ---


@patch("src.data_aggregator.core.create_tar_gz_bundle_stream")
def test_process_and_stage_batch_happy_path(mock_create_bundle, mock_lambda_context):
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_bundle_file = MagicMock(spec=io.BytesIO)
    mock_content_hash = "fake_tar_hash_456"
    mock_create_bundle.return_value.__enter__.return_value = (
        mock_bundle_file,
        mock_content_hash,
    )
    test_records = [
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "f1.txt", "size": 10}}}
    ]
    # The function now only needs the distribution bucket and a bundle key
    distribution_bucket, bundle_key = "d-b", "key.tar.gz"

    # 2. ACT
    # Call the simplified function with the new arguments
    process_and_stage_batch(
        records=test_records,
        s3_client=mock_s3_client,
        distribution_bucket=distribution_bucket,
        bundle_key=bundle_key,
        context=mock_lambda_context,
    )

    # 3. ASSERT
    # Assert that the bundler was called correctly
    mock_create_bundle.assert_called_once_with(
        mock_s3_client, test_records, mock_lambda_context
    )
    # Assert that ONLY the single upload method was called with the correct args
    mock_s3_client.upload_gzipped_bundle.assert_called_once_with(
        bucket=distribution_bucket,
        key=bundle_key,
        file_obj=mock_bundle_file,
        content_hash=mock_content_hash,
    )
    # Assert that the copy method is NEVER called
    mock_s3_client.copy_bundle.assert_not_called()


def test_process_and_stage_batch_raises_error_for_empty_records(mock_lambda_context):
    """Verifies ValueError for an empty list of records."""
    # 1. ARRANGE
    # No complex arrangement needed for this test.

    # ACT & ASSERT
    with pytest.raises(ValueError, match="Cannot process an empty batch."):
        # Correctly call the function with its new 5-argument signature.
        # The values don't matter much since it will fail on the empty list first.
        process_and_stage_batch(
            records=[],
            s3_client=MagicMock(),
            distribution_bucket="any-dist-bucket",
            bundle_key="any-bundle-key",
            context=mock_lambda_context,
        )

# --- Core Logic and Security Tests ---


def test_create_tar_gz_bundle_stream_creates_valid_archive(mock_lambda_context):
    """Tests the happy path for creating a valid archive."""
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    file1_content, file2_content = b"file1", b"file2"
    mock_s3_client.get_file_content_stream.side_effect = [
        io.BytesIO(file1_content),
        io.BytesIO(file2_content),
    ]
    records = [
        {
            "s3": {
                "bucket": {"name": "b"},
                "object": {"key": "f1.txt", "size": len(file1_content)},
            }
        },
        {
            "s3": {
                "bucket": {"name": "b"},
                "object": {"key": "d/f2.log", "size": len(file2_content)},
            }
        },
    ]

    # 2. ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        f,
        returned_hash,
    ):
        bundle_content = f.read()

    # 3. ASSERT
    actual_hash = hashlib.sha256(bundle_content).hexdigest()
    assert returned_hash == actual_hash
    with (
        io.BytesIO(bundle_content) as bio,
        tarfile.open(fileobj=bio, mode="r:gz") as tar,
    ):
        assert sorted(tar.getnames()) == sorted(["d/f2.log", "f1.txt"])
        assert tar.extractfile("f1.txt").read() == file1_content


@pytest.mark.parametrize(
    "original_key, expected_safe_key",
    [
        # ─── Traversal & absolute paths ────────────────────────────────────────────
        ("foo/../../etc/passwd", None),  # Up-level traversal ⇒ reject
        ("/etc/passwd", "etc/passwd"),  # Leading slash becomes relative
        (
            "C:\\Windows\\System32.dll",
            "Windows/System32.dll",
        ),  # Strip drive + backslashes
        (
            "C:/Windows/System32.dll",
            "Windows/System32.dll",
        ),  # Same with forward slashes
        ("foo/./bar//baz.txt", "foo/bar/baz.txt"),  # Collapsed ./ and // segments
        ("foo\\..\\bar.txt", "bar.txt"),  # Mixed slashes with traversal
        # ─── Benign oddities ───────────────────────────────────────────────────────
        ("my folder/my report.docx", "my folder/my report.docx"),  # Spaces
        ("data/folder/", "data/folder"),  # Trailing slash (“folder object”)
        ("你好/世界.txt", "你好/世界.txt"),  # UTF-8
        ("a///b//c.txt", "a/b/c.txt"),  # Multiple consecutive slashes
        ("aux", "aux"),  # Windows device name – allowed
        ("CON.txt", "CON.txt"),  # Another device name
        # ─── Control / percent-encoded / dot keys ─────────────────────────────────
        ("data/file\0name.txt", None),  # NUL byte ⇒ reject
        ("bad\rname.txt", None),  # Other control char
        (
            "foo/%2e%2e/%2e%2e/passwd",
            "foo/%2e%2e/%2e%2e/passwd",
        ),  # Encoded “..” left verbatim
        ("", None),  # Empty key ⇒ reject
        (".", None),  # Just "." ⇒ reject
        ("./", None),  # "./" with slash ⇒ reject
        ("././", None),  # Repeated "./" ⇒ reject
        # ─── Pathological length / trailing chars ─────────────────────────────────
        ("a" * 1025 + ".txt", None),  # >1024-byte key (S3 would reject)
        ("trickyfile.txt. ", "trickyfile.txt. "),  # Trailing dot/space (Windows quirk)
        # ─── Unicode-normalisation twins (both allowed, distinct) ─────────────────
        ("e\u0301.txt", "e\u0301.txt"),  # "é" composed with accent
        ("é.txt", "é.txt"),  # NFC-composed form
    ],
)
def test_sanitize_s3_key(original_key, expected_safe_key):
    """Tests the _sanitize_s3_key helper function in isolation."""
    # 2. ACT
    result = _sanitize_s3_key(original_key)

    # 3. ASSERT
    assert result == expected_safe_key


# --- Edge Case and Robustness Tests ---


def test_create_tar_gz_bundle_stream_handles_empty_file(mock_lambda_context):
    """Verifies the bundler correctly handles a 0-byte file."""
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_s3_client.get_file_content_stream.return_value = io.BytesIO(b"")
    records = [
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "empty.txt", "size": 0}}}
    ]

    # 2. ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        f,
        _,
    ):
        bundle_content = f.read()

    # 3. ASSERT
    with (
        io.BytesIO(bundle_content) as bio,
        tarfile.open(fileobj=bio, mode="r:gz") as tar,
    ):
        member = tar.getmember("empty.txt")
        assert member.size == 0


def test_create_tar_gz_bundle_stream_raises_on_timeout(mock_lambda_context):
    """Verifies the timeout guard aborts processing."""
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    records = [
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "f0.txt", "size": 7}}}
    ]
    mock_lambda_context.get_remaining_time_in_millis.return_value = 5000

    # 2. ACT & 3. ASSERT
    with pytest.raises(BundlingTimeoutError):
        with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context):
            pass  # This block should not be reached

    mock_s3_client.get_file_content_stream.assert_not_called()


def test_create_tar_gz_bundle_stream_handles_size_mismatch(mock_lambda_context):
    """
    Verifies the bundler skips a file if its actual content size does not
    match the size reported in the S3 event metadata.
    """
    # 1. ARRANGE
    mock_s3_client = MagicMock()
    mock_s3_client.get_file_content_stream.return_value = io.BytesIO(b"ten bytes!")
    records = [
        {
            "s3": {
                "bucket": {"name": "b"},
                "object": {"key": "bad_size.txt", "size": 100},
            }
        }
    ]

    # 2. ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        f,
        _,
    ):
        bundle_content = f.read()

    # 3. ASSERT
    # FIX: The file should now be skipped entirely, resulting in an empty bundle.
    with (
        io.BytesIO(bundle_content) as bio,
        tarfile.open(fileobj=bio, mode="r:gz") as tar,
    ):
        assert not tar.getmembers(), (
            "The bundle should be empty after skipping the bad file."
        )


def test_buffer_and_validate_ok():
    """Tests the happy path where the size matches."""
    # 1. ARRANGE
    data = b"Hello world!"

    # 2. ACT
    result = _buffer_and_validate(io.BytesIO(data), expected_size=len(data))

    # 3. ASSERT
    assert result is not None
    buf, size = result

    assert size == len(data)
    assert buf.tell() == 0
    assert buf.read() == data
    buf.close()


def test_buffer_and_validate_size_mismatch():
    """Tests that a size mismatch returns None."""
    # 1. ARRANGE
    data = b"abc"

    # 2. ACT
    result = _buffer_and_validate(io.BytesIO(data), expected_size=10)

    # 3. ASSERT
    assert result is None


def test_buffer_and_validate_spills_to_disk():
    """Tests that the buffer correctly spills to disk for large objects."""
    # 1. ARRANGE
    # Use a tiny threshold so we don't allocate lots of RAM during the test
    threshold = 1024  # 1 KiB
    big_blob = os.urandom(threshold + 100)  # Exceed threshold

    # 2. ACT
    result = _buffer_and_validate(
        io.BytesIO(big_blob),
        expected_size=len(big_blob),
        spool_threshold=threshold,  # Force rollover
    )

    # 3. ASSERT
    assert result is not None
    buf, size = result

    assert size == len(big_blob)

    # SpooledTemporaryFile sets _rolled to True once it hits disk
    if hasattr(buf, "_rolled"):
        assert buf._rolled is True

    buf.close()

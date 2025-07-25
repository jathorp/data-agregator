# tests/unit/test_core.py

import hashlib
import io
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

# Import all necessary functions and exceptions from the core module
from src.data_aggregator.core import (
    MAX_BUNDLE_ON_DISK_BYTES,
    create_tar_gz_bundle_stream,
    process_and_stage_batch,
    _buffer_and_validate,
    _sanitize_s3_key,
)
from src.data_aggregator.schemas import S3EventRecord


@pytest.fixture
def mock_lambda_context() -> MagicMock:
    """Provides a mock LambdaContext object that passes timeout checks."""
    context = MagicMock(spec=LambdaContext)
    context.get_remaining_time_in_millis.return_value = 300_000
    return context


# --- High-Level Orchestration Tests (`process_and_stage_batch`) ---


@patch("src.data_aggregator.core.create_tar_gz_bundle_stream")
def test_process_and_stage_batch_happy_path(mock_create_bundle, mock_lambda_context):
    """Tests the happy path where all records are processed."""
    # ARRANGE
    mock_s3_client = MagicMock()
    mock_bundle_file = io.BytesIO(b"bundle data")
    mock_hash = "fake_hash"
    test_records: list[S3EventRecord] = [
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "f1.txt", "size": 10}}}
    ]

    # Update the mock to return the new 3-item tuple
    mock_create_bundle.return_value.__enter__.return_value = (
        mock_bundle_file,
        mock_hash,
        test_records,
    )

    # ACT
    sha256_hash, processed, remaining = process_and_stage_batch(
        records=test_records,
        s3_client=mock_s3_client,
        distribution_bucket="dist-bucket",
        bundle_key="bundle.tar.gz",
        context=mock_lambda_context,
    )

    # ASSERT
    mock_create_bundle.assert_called_once_with(
        mock_s3_client, test_records, mock_lambda_context
    )
    mock_s3_client.upload_gzipped_bundle.assert_called_once_with(
        bucket="dist-bucket",
        key="bundle.tar.gz",
        file_obj=mock_bundle_file,
        content_hash=mock_hash,
    )
    assert sha256_hash == mock_hash
    assert len(processed) == 1
    assert not remaining  # No records should be remaining


def test_process_and_stage_batch_raises_for_empty_records(mock_lambda_context):
    """Verifies ValueError for an empty list of records."""
    with pytest.raises(ValueError, match="Cannot process an empty batch."):
        process_and_stage_batch([], MagicMock(), "dist", "key", mock_lambda_context)


# --- Core Bundling Routine Tests (`create_tar_gz_bundle_stream`) ---


def test_create_tar_gz_bundle_stream_happy_path(mock_lambda_context):
    """Tests creating a valid archive with multiple files."""
    # ARRANGE
    mock_s3_client = MagicMock()
    file1, file2 = b"file1 content", b"file2 content"
    mock_s3_client.get_file_content_stream.side_effect = [
        io.BytesIO(file1),
        io.BytesIO(file2),
    ]
    records: list[S3EventRecord] = [
        {
            "s3": {
                "bucket": {"name": "b"},
                "object": {"key": "f1.txt", "size": len(file1)},
            }
        },
        {
            "s3": {
                "bucket": {"name": "b"},
                "object": {"key": "d/f2.log", "size": len(file2)},
            }
        },
    ]

    # ACT
    # Unpack all three return values
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        f,
        r_hash,
        p_records,
    ):
        bundle_content = f.read()

    # ASSERT
    assert hashlib.sha256(bundle_content).hexdigest() == r_hash
    assert len(p_records) == 2  # Check all records were processed
    with (
        io.BytesIO(bundle_content) as bio,
        tarfile.open(fileobj=bio, mode="r:gz") as tar,
    ):
        assert sorted(tar.getnames()) == sorted(["d/f2.log", "f1.txt"])
        assert tar.extractfile("f1.txt").read() == file1


def test_create_tar_gz_bundle_stream_stops_gracefully_on_timeout(mock_lambda_context):
    """Verifies the bundler stops processing but doesn't error on timeout."""
    # ARRANGE
    mock_s3_client = MagicMock()
    mock_s3_client.get_file_content_stream.return_value = io.BytesIO(b"content")
    records: list[S3EventRecord] = [
        {"s3": {"object": {"key": "f1.txt", "size": 7}, "bucket": {"name": "b"}}},
        {"s3": {"object": {"key": "f2.txt", "size": 5}, "bucket": {"name": "b"}}},
    ]
    mock_lambda_context.get_remaining_time_in_millis.side_effect = [20000, 5000]

    # ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        _,
        _,
        processed_records,
    ):
        pass  # The action is the iteration itself

    # ASSERT
    mock_s3_client.get_file_content_stream.assert_called_once()
    assert len(processed_records) == 1
    assert processed_records[0]["s3"]["object"]["key"] == "f1.txt"


def test_create_tar_gz_bundle_stream_stops_gracefully_on_disk_limit(
    mock_lambda_context,
):
    """Verifies the bundler stops processing when the disk limit is reached."""
    # ARRANGE
    mock_s3_client = MagicMock()
    # Make the first file large enough to trigger the check for the second file
    file1_size = MAX_BUNDLE_ON_DISK_BYTES - 100
    mock_s3_client.get_file_content_stream.return_value = io.BytesIO(b"a" * file1_size)
    records: list[S3EventRecord] = [
        {
            "s3": {
                "object": {"key": "f1.txt", "size": file1_size},
                "bucket": {"name": "b"},
            }
        },
        {"s3": {"object": {"key": "f2.txt", "size": 200}, "bucket": {"name": "b"}}},
    ]

    # ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        _,
        _,
        processed_records,
    ):
        pass

    # ASSERT
    mock_s3_client.get_file_content_stream.assert_called_once()
    assert len(processed_records) == 1
    assert processed_records[0]["s3"]["object"]["key"] == "f1.txt"


def test_create_tar_gz_bundle_stream_skips_mismatched_size_file(mock_lambda_context):
    """Verifies a file is skipped if its actual size mismatches its metadata."""
    # ARRANGE
    mock_s3_client = MagicMock()
    mock_s3_client.get_file_content_stream.return_value = io.BytesIO(
        b"actually 10 bytes"
    )
    records: list[S3EventRecord] = [
        {"s3": {"object": {"key": "bad.txt", "size": 100}, "bucket": {"name": "b"}}}
    ]

    # ACT
    with create_tar_gz_bundle_stream(mock_s3_client, records, mock_lambda_context) as (
        f,
        _,
        p_records,
    ):
        bundle_content = f.read()

    # ASSERT
    assert len(p_records) == 0  # The bad record should not be in the processed list
    with (
        io.BytesIO(bundle_content) as bio,
        tarfile.open(fileobj=bio, mode="r:gz") as tar,
    ):
        assert not tar.getmembers()


# --- Helper Function Tests ---


@pytest.mark.parametrize(
    "key, safe_key",
    [
        ("foo/../../etc/passwd", None),
        ("/etc/passwd", "etc/passwd"),
        ("C:\\Windows\\System32.dll", "Windows/System32.dll"),
        ("foo/./bar//baz.txt", "foo/bar/baz.txt"),
        ("a" * 1025, None),
    ],
)
def test_sanitize_s3_key(key, safe_key):
    assert _sanitize_s3_key(key) == safe_key


def test_buffer_and_validate_ok():
    data = b"Hello world"
    buf, size = _buffer_and_validate(io.BytesIO(data), expected_size=len(data))
    assert size == len(data)
    assert buf.read() == data
    buf.close()


def test_buffer_and_validate_size_mismatch():
    assert _buffer_and_validate(io.BytesIO(b"abc"), expected_size=10) is None

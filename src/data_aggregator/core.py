# src/data_aggregator/core.py

"""
Core business logic for creating and staging data bundles.

This module contains the primary logic for the Data Aggregator service. Its main
entry point, `create_tar_gz_bundle_stream`, reads multiple S3 objects, validates
them, and bundles them into a single, secure, compressed tarball (`.tar.gz`).

The implementation is heavily optimized for security, correctness, and robust
operation within a memory-constrained AWS Lambda environment.
"""

import hashlib
import io
import logging
import os
import re
import tarfile
from contextlib import closing, contextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Iterator, List, Optional, Tuple, cast

from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import S3Client
from .exceptions import ObjectNotFoundError
from .schemas import S3EventRecord

logger = logging.getLogger(__name__)

# --- Tunables - future todo move to environment variables ---
SPOOL_FILE_MAX_SIZE_BYTES: int = 64 * 1024 * 1024  # 64 MiB – spills to /tmp after this
TIMEOUT_GUARD_THRESHOLD_MS: int = 10_000  # Bail out when < 10s remaining
MAX_BUNDLE_ON_DISK_BYTES = 400 * 1024 * 1024  # e.g., 400MB to be safe


# --- Helpers ---
def _sanitize_s3_key(key: str) -> Optional[str]:
    """Return a safe, relative POSIX path or None if the key is disallowed."""
    try:
        if any(ord(c) < 0x1F for c in key) or len(key.encode("utf-8")) > 1024:
            return None
        key_no_drive = re.sub(r"^[a-zA-Z]:", "", key)
        path_with_fwd_slashes = key_no_drive.replace("\\", "/")
        normalized_path = os.path.normpath(path_with_fwd_slashes)
        safe_key = normalized_path.lstrip("/")
        if safe_key.startswith("..") or safe_key in {"", "."}:
            return None
        return safe_key
    except TypeError:
        return None


def _buffer_and_validate(
    stream: BinaryIO,
    expected_size: int,
    spool_threshold: int = SPOOL_FILE_MAX_SIZE_BYTES,
) -> Optional[Tuple[BinaryIO, int]]:
    """
    Read *stream* into a SpooledTemporaryFile (in-RAM up to *spool_threshold*,
    then /tmp on disk) while counting bytes.

    Returns (file_like, actual_size) on success, or None when the
    byte-count mismatches *expected_size*.
    """
    tmp = SpooledTemporaryFile(max_size=spool_threshold, mode="w+b")

    copied = 0
    for chunk in iter(lambda: stream.read(64 * 1024), b""):
        tmp.write(chunk)
        copied += len(chunk)

    if copied != expected_size:
        tmp.close()
        return None

    tmp.seek(0)  # rewind for reading
    return cast(BinaryIO, tmp), copied


class HashingFileWrapper(io.BufferedIOBase):
    """
    Proxy object that tees everything written to an underlying file-like
    object into a SHA-256 hash.
    """

    def __init__(self, fileobj: BinaryIO):
        self._fileobj = fileobj
        self._hasher = hashlib.sha256()

    def write(self, data: bytes) -> int:
        self._hasher.update(data)
        return self._fileobj.write(data)

    def flush(self) -> None:
        if not self._fileobj.closed:
            self._fileobj.flush()

    def close(self) -> None:
        pass  # The parent context manager is responsible for closing.

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()

    def __getattr__(self, attr):
        return getattr(self._fileobj, attr)


# --- Core Bundling Routine ---
@contextmanager
def create_tar_gz_bundle_stream(
        s3_client: S3Client, records: List[S3EventRecord], context: LambdaContext
) -> Iterator[Tuple[BinaryIO, str, List[S3EventRecord]]]:
    """
    Stream-creates a compressed tarball from S3 objects, stopping gracefully
    on timeout or disk space constraints. Catches errors for individual files.

    Yields the bundle stream, its hash, and a list of the records that were
    successfully processed into the bundle.
    """
    output_spool_file: BinaryIO = SpooledTemporaryFile(  # type: ignore[assignment]
        max_size=SPOOL_FILE_MAX_SIZE_BYTES, mode="w+b"
    )
    hashing_writer = HashingFileWrapper(output_spool_file)
    processed_records: List[S3EventRecord] = []
    bytes_written = 0

    try:
        with tarfile.open(
                mode="w:gz",
                fileobj=cast(BinaryIO, hashing_writer),
                format=tarfile.PAX_FORMAT,
        ) as tar:
            logger.debug(f"Starting to process a batch of {len(records)} records.")

            for i, record in enumerate(records):
                # --- START OF THE TRY BLOCK FOR A SINGLE RECORD ---
                try:
                    # 1. Gracefully stop if nearing timeout
                    if context.get_remaining_time_in_millis() < TIMEOUT_GUARD_THRESHOLD_MS:
                        logger.warning("Timeout threshold reached. Finalizing bundle.")
                        break

                    metadata_size = record["s3"]["object"]["size"]

                    # 2. Gracefully stop if predicted disk usage is too high
                    if (bytes_written + metadata_size) > MAX_BUNDLE_ON_DISK_BYTES:
                        logger.warning(
                            "Predicted disk usage exceeds limit. Finalizing bundle."
                        )
                        break

                    original_key = record["s3"]["object"]["key"]
                    safe_key = _sanitize_s3_key(original_key)
                    if safe_key is None:
                        logger.warning("Skipping invalid S3 key.", extra={"key": original_key})
                        continue

                    bucket = record["s3"]["bucket"]["name"]

                    # 3. Decide how to handle the file based on its size
                    if metadata_size < SPOOL_FILE_MAX_SIZE_BYTES:
                        # Small file: buffer first to validate size
                        stream = s3_client.get_file_content_stream(bucket, original_key)
                        with closing(stream):
                            buffered = _buffer_and_validate(stream, metadata_size)

                        if buffered is None:
                            logger.warning(
                                "Size mismatch between S3 metadata and actual object. Skipping.",
                                extra={"key": original_key}
                            )
                            continue
                        fileobj_for_tarball, actual_size = buffered
                    else:
                        # Large file: stream directly to conserve disk space
                        logger.debug(
                            "Streaming large file directly to tarball.", extra={"key": original_key}
                        )
                        fileobj_for_tarball = s3_client.get_file_content_stream(
                            bucket, original_key
                        )
                        actual_size = metadata_size

                    # 4. Build tar header and add the file
                    tarinfo = tarfile.TarInfo(name=safe_key)
                    tarinfo.size = actual_size
                    tarinfo.mtime = 0
                    tarinfo.uid = tarinfo.gid = 0
                    tarinfo.uname = tarinfo.gname = "root"

                    with closing(fileobj_for_tarball):
                        tar.addfile(tarinfo, fileobj=fileobj_for_tarball)

                    # 5. On success, update tracking variables
                    processed_records.append(record)
                    bytes_written += ((actual_size + 511) // 512) * 512

                # --- START OF THE EXCEPTION HANDLING BLOCK ---
                except ObjectNotFoundError:
                    # This gracefully handles the case where the S3 object was deleted
                    # between the event notification and this processing step.
                    logger.debug(
                        "S3 object for record not found, it may have been deleted. Skipping.",
                        extra={"key": record["s3"]["object"]["key"]},
                    )
                    continue  # Move to the next record in the batch

                except Exception:
                    # This is a generic catch-all for any other unexpected error
                    # that occurs while processing a single file.
                    key_for_logging = record.get("s3", {}).get("object", {}).get("key", "unknown")
                    logger.exception(
                        "An unexpected error occurred when adding a file to the tarball. Skipping.",
                        extra={"key": key_for_logging},
                    )
                    continue  # Also move to the next record
                # --- END OF THE EXCEPTION HANDLING BLOCK ---

        # 6. Finalize and yield results
        logger.info(
            f"Finished processing batch. Added {len(processed_records)} records to bundle."
        )

        hashing_writer.flush()
        sha256_hash = hashing_writer.hexdigest()
        output_spool_file.seek(0)
        yield cast(BinaryIO, output_spool_file), sha256_hash, processed_records

    finally:
        output_spool_file.close()


# --- High-Level Orchestrator ---
def process_and_stage_batch(
    records: List[S3EventRecord],
    s3_client: S3Client,
    distribution_bucket: str,
    bundle_key: str,
    context: LambdaContext,
) -> Tuple[str, List[S3EventRecord], List[S3EventRecord]]:
    """
    Creates a bundle, uploads it, and returns the hash, a list of processed
    records, and a list of any remaining (unprocessed) records.
    """
    if not records:
        raise ValueError("Cannot process an empty batch.")

    with create_tar_gz_bundle_stream(s3_client, records, context) as (
        bundle,
        sha256_hash,
        processed_records,
    ):
        s3_client.upload_gzipped_bundle(
            bucket=distribution_bucket,
            key=bundle_key,
            file_obj=bundle,
            content_hash=sha256_hash,
        )

    logger.info(
        "Successfully staged bundle to distribution bucket",
        extra={
            "key": bundle_key,
            "hash": sha256_hash,
            "processed_count": len(processed_records),
            "initial_count": len(records),
        },
    )

    # Calculate the records that were not processed
    remaining_records = [r for r in records if r not in processed_records]

    # Return the hash and both lists
    return sha256_hash, processed_records, remaining_records

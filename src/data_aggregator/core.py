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
from .config import AppConfig
from .exceptions import (
    BundleCreationError,
    DiskSpaceError,
    InvalidS3EventError,
    MemoryLimitError,
    ObjectNotFoundError,
    S3AccessDeniedError,
    S3ObjectNotFoundError,
    S3ThrottlingError,
    S3TimeoutError,
    ValidationError,
)
from .schemas import S3EventRecord

logger = logging.getLogger(__name__)


# --- Helpers ---
def _sanitize_s3_key(key: str) -> str:
    """Return a safe, relative POSIX path or raise ValidationError if the key is disallowed."""
    try:
        if any(ord(c) < 0x1F for c in key) or len(key.encode("utf-8")) > 1024:
            raise ValidationError(
                "S3 key contains invalid characters or exceeds length limit",
                error_code="INVALID_S3_KEY_FORMAT",
                context={"key": key, "key_length": len(key.encode("utf-8"))}
            )
        key_no_drive = re.sub(r"^[a-zA-Z]:", "", key)
        path_with_fwd_slashes = key_no_drive.replace("\\", "/")
        normalized_path = os.path.normpath(path_with_fwd_slashes)
        safe_key = normalized_path.lstrip("/")
        if safe_key.startswith("..") or safe_key in {"", "."}:
            raise ValidationError(
                "S3 key contains path traversal or invalid path components",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "normalized_path": safe_key}
            )
        return safe_key
    except TypeError as e:
        raise ValidationError(
            "S3 key is not a valid string",
            error_code="INVALID_S3_KEY_TYPE",
            context={"key": key, "type": type(key).__name__}
        ) from e


def _buffer_and_validate(
    stream: BinaryIO,
    expected_size: int,
    spool_threshold: int,
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
    s3_client: S3Client, records: List[S3EventRecord], context: LambdaContext, config: AppConfig
) -> Iterator[Tuple[BinaryIO, str, List[S3EventRecord]]]:
    """
    Stream-creates a compressed tarball from S3 objects, stopping gracefully
    on timeout or disk space constraints. Catches errors for individual files.

    Yields the bundle stream, its hash, and a list of the records that were
    successfully processed into the bundle.
    """
    output_spool_file: BinaryIO = SpooledTemporaryFile(  # type: ignore[assignment]
        max_size=config.spool_file_max_size_bytes, mode="w+b"
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
                    if (
                        context.get_remaining_time_in_millis()
                        < config.timeout_guard_threshold_ms
                    ):
                        logger.warning("Timeout threshold reached. Finalizing bundle.")
                        break

                    metadata_size = record["s3"]["object"]["size"]

                    # 2. Gracefully stop if predicted disk usage is too high
                    if (bytes_written + metadata_size) > config.max_bundle_on_disk_bytes:
                        logger.warning(
                            "Predicted disk usage exceeds limit. Finalizing bundle."
                        )
                        break

                    original_key = record["s3"]["object"]["key"]
                    safe_key = _sanitize_s3_key(original_key)

                    bucket = record["s3"]["bucket"]["name"]

                    # 3. Decide how to handle the file based on its size
                    if metadata_size < config.spool_file_max_size_bytes:
                        # Small file: buffer first to validate size
                        stream = s3_client.get_file_content_stream(bucket, original_key)
                        with closing(stream):
                            buffered = _buffer_and_validate(stream, metadata_size, config.spool_file_max_size_bytes)

                        if buffered is None:
                            logger.warning(
                                "Size mismatch between S3 metadata and actual object. Skipping.",
                                extra={"key": original_key},
                            )
                            continue
                        fileobj_for_tarball, actual_size = buffered
                    else:
                        # Large file: stream directly to conserve disk space
                        logger.debug(
                            "Streaming large file directly to tarball.",
                            extra={"key": original_key},
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
                except ValidationError as e:
                    # Handle invalid S3 keys or validation errors
                    logger.warning(
                        f"Validation error for S3 key: {e}",
                        extra={
                            "key": original_key,
                            "error_code": e.error_code,
                            "error_context": e.context,
                            "correlation_id": e.correlation_id
                        }
                    )
                    continue  # Skip this record and move to the next

                except (S3ObjectNotFoundError, ObjectNotFoundError):
                    # This gracefully handles the case where the S3 object was deleted
                    # between the event notification and this processing step.
                    logger.debug(
                        "S3 object for record not found, it may have been deleted. Skipping.",
                        extra={"key": record["s3"]["object"]["key"]},
                    )
                    continue  # Move to the next record in the batch

                except S3AccessDeniedError as e:
                    # Handle access denied errors
                    logger.warning(
                        f"Access denied for S3 object: {e}",
                        extra={
                            "key": original_key,
                            "bucket": bucket,
                            "error_code": e.error_code,
                            "correlation_id": e.correlation_id
                        }
                    )
                    continue  # Skip this record

                except (S3ThrottlingError, S3TimeoutError) as e:
                    # Handle retryable S3 errors - log but continue processing other files
                    logger.warning(
                        f"Retryable S3 error for object: {e}",
                        extra={
                            "key": original_key,
                            "bucket": bucket,
                            "error_code": e.error_code,
                            "correlation_id": e.correlation_id,
                            "retryable": True
                        }
                    )
                    continue  # Skip this record for now

                except MemoryError:
                    # Handle memory errors by raising a specific exception
                    raise MemoryLimitError(
                        "Insufficient memory to process file",
                        error_code="MEMORY_LIMIT_EXCEEDED",
                        context={
                            "key": original_key,
                            "file_size": metadata_size,
                            "bytes_written": bytes_written
                        }
                    )

                except OSError as e:
                    # Handle disk space and other OS errors
                    if e.errno == 28:  # No space left on device
                        raise DiskSpaceError(
                            "Insufficient disk space to process file",
                            error_code="DISK_SPACE_EXCEEDED",
                            context={
                                "key": original_key,
                                "file_size": metadata_size,
                                "bytes_written": bytes_written
                            }
                        ) from e
                    else:
                        # Other OS errors
                        logger.warning(
                            f"OS error while processing file: {e}",
                            extra={
                                "key": original_key,
                                "errno": e.errno,
                                "strerror": e.strerror
                            }
                        )
                        continue

                except tarfile.TarError as e:
                    # Handle tarfile creation errors
                    raise BundleCreationError(
                        f"Failed to add file to tarball: {e}",
                        error_code="TAR_CREATION_ERROR",
                        context={
                            "key": original_key,
                            "file_size": metadata_size,
                            "tar_error": str(e)
                        }
                    ) from e

                except Exception as e:
                    # This is a generic catch-all for any other unexpected error
                    # that occurs while processing a single file.
                    key_for_logging = (
                        record.get("s3", {}).get("object", {}).get("key", "unknown")
                    )
                    logger.exception(
                        "An unexpected error occurred when adding a file to the tarball. Skipping.",
                        extra={
                            "key": key_for_logging,
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        },
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
    config: AppConfig,
) -> Tuple[str, List[S3EventRecord], List[S3EventRecord]]:
    """
    Creates a bundle, uploads it, and returns the hash, a list of processed
    records, and a list of any remaining (unprocessed) records.
    """
    # Input validation
    if not records:
        raise InvalidS3EventError(
            "Cannot process an empty batch of records",
            error_code="EMPTY_BATCH",
            context={"records_count": len(records)}
        )
    
    if not distribution_bucket or not bundle_key:
        raise ValidationError(
            "Distribution bucket and bundle key must be provided",
            error_code="MISSING_REQUIRED_PARAMETERS",
            context={
                "distribution_bucket": distribution_bucket,
                "bundle_key": bundle_key
            }
        )

    try:
        with create_tar_gz_bundle_stream(s3_client, records, context, config) as (
            bundle,
            sha256_hash,
            processed_records,
        ):
            # Upload the bundle to S3
            try:
                s3_client.upload_gzipped_bundle(
                    bucket=distribution_bucket,
                    key=bundle_key,
                    file_obj=bundle,
                    content_hash=sha256_hash,
                )
            except Exception as e:
                # Wrap upload errors in our exception hierarchy
                raise BundleCreationError(
                    f"Failed to upload bundle to S3: {e}",
                    error_code="BUNDLE_UPLOAD_FAILED",
                    context={
                        "bucket": distribution_bucket,
                        "key": bundle_key,
                        "hash": sha256_hash,
                        "processed_count": len(processed_records),
                        "upload_error": str(e)
                    }
                ) from e

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
        
    except (MemoryLimitError, DiskSpaceError, BundleCreationError):
        # Re-raise our specific exceptions without modification
        raise
    except Exception as e:
        # Wrap any other unexpected errors
        raise BundleCreationError(
            f"Unexpected error during batch processing: {e}",
            error_code="BATCH_PROCESSING_ERROR",
            context={
                "records_count": len(records),
                "distribution_bucket": distribution_bucket,
                "bundle_key": bundle_key,
                "error_type": type(e).__name__
            }
        ) from e

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
import shutil
import tarfile
from contextlib import closing, contextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Iterator, cast

from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import S3Client
from .config import AppConfig
from .exceptions import (
    BundleCreationError,
    DiskSpaceError,
    MemoryLimitError,
    ObjectNotFoundError,
    S3AccessDeniedError,
    S3ObjectNotFoundError,
    S3ThrottlingError,
    S3TimeoutError,
)
from .schemas import S3EventNotificationRecord

logger = logging.getLogger(__name__)


# --- Helpers ---
def _buffer_and_validate(
    stream: BinaryIO,
    expected_size: int,
    spool_threshold: int,
) -> tuple[BinaryIO, int] | None:
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
    s3_client: S3Client,
    # --- REFACTOR ---: The function now expects a list of Pydantic models.
    records: list[S3EventNotificationRecord],
    context: LambdaContext,
    config: AppConfig,
) -> Iterator[tuple[BinaryIO, str, list[S3EventNotificationRecord]]]:
    """
    Stream-creates a compressed tarball from S3 objects, stopping gracefully
    on timeout or disk space constraints. Catches errors for individual files.

    Yields the bundle stream, its hash, and a list of the records that were
    successfully processed into the bundle.
    """
    output_spool_file: BinaryIO = cast(
        BinaryIO,
        SpooledTemporaryFile(max_size=config.spool_file_max_size_bytes, mode="w+b"),
    )
    hashing_writer = HashingFileWrapper(output_spool_file)
    # --- REFACTOR ---: The list of processed records now also contains Pydantic models.
    processed_records: list[S3EventNotificationRecord] = []
    bytes_written = 0

    try:
        with tarfile.open(
            mode="w:gz",
            fileobj=cast(BinaryIO, hashing_writer),
            format=tarfile.PAX_FORMAT,
        ) as tar:
            logger.debug(f"Starting to process a batch of {len(records)} records.")

            for i, record in enumerate(records):
                # --- REFACTOR ---: Access data via attributes from the trusted Pydantic model.
                # The schema change provides both the original key (for S3 fetch) and
                # the sanitized key (for the tarball archive name).
                bucket = record.s3.bucket.name
                original_key_to_fetch = record.s3.object.original_key
                safe_key_for_tarball = record.s3.object.key
                metadata_size = record.s3.object.size

                try:
                    # Graceful termination checks (logic unchanged)
                    if (
                        context.get_remaining_time_in_millis()
                        < config.timeout_guard_threshold_ms
                    ):
                        logger.warning("Timeout threshold reached. Finalizing bundle.")
                        break
                    if (
                        bytes_written + metadata_size
                    ) > config.max_bundle_on_disk_bytes:
                        logger.warning(
                            "Predicted disk usage exceeds limit. Finalizing bundle."
                        )
                        break

                    # File handling logic (unchanged, but uses new variables)
                    if metadata_size < config.spool_file_max_size_bytes:
                        stream = s3_client.get_file_content_stream(
                            bucket, original_key_to_fetch
                        )
                        with closing(stream):
                            buffered = _buffer_and_validate(
                                stream, metadata_size, config.spool_file_max_size_bytes
                            )

                        if buffered is None:
                            logger.warning(
                                "Size mismatch. Skipping.",
                                extra={"key": original_key_to_fetch},
                            )
                            continue
                        fileobj_for_tarball, actual_size = buffered
                    else:
                        logger.debug(
                            "Streaming large file.",
                            extra={"key": original_key_to_fetch},
                        )
                        fileobj_for_tarball = s3_client.get_file_content_stream(
                            bucket, original_key_to_fetch
                        )
                        actual_size = metadata_size

                    # Tarball entry creation (uses the sanitized key for the name)
                    tarinfo = tarfile.TarInfo(name=safe_key_for_tarball)
                    tarinfo.size = actual_size
                    tarinfo.mtime = 0
                    tarinfo.uid = tarinfo.gid = 0
                    tarinfo.uname = tarinfo.gname = "root"

                    with closing(fileobj_for_tarball):
                        tar.addfile(tarinfo, fileobj=fileobj_for_tarball)

                    processed_records.append(record)
                    bytes_written += ((actual_size + 511) // 512) * 512

                # The 'except ValidationError' block is completely removed as this
                # validation is now handled upstream by the handler.
                except (S3ObjectNotFoundError, ObjectNotFoundError):
                    logger.debug(
                        "S3 object not found. Skipping.",
                        extra={"key": original_key_to_fetch},
                    )
                    continue
                except S3AccessDeniedError as e:
                    logger.warning(
                        f"Access denied for S3 object: {e}",
                        extra={"key": original_key_to_fetch},
                    )
                    continue
                except (S3ThrottlingError, S3TimeoutError) as e:
                    logger.warning(
                        f"Retryable S3 error for object: {e}",
                        extra={"key": original_key_to_fetch},
                    )
                    continue
                except MemoryError:
                    raise MemoryLimitError(
                        "Insufficient memory", context={"key": original_key_to_fetch}
                    )

                except OSError as e:
                    if e.errno == 28:  # No space left on device
                        try:
                            disk_usage = shutil.disk_usage("/tmp")
                            available_bytes = disk_usage.free
                        except Exception:
                            available_bytes = -1

                        # Use the size of the file we failed on as a reasonable
                        # estimate for the required bytes.
                        required_bytes_estimate = metadata_size

                        raise DiskSpaceError(
                            # Positional arguments for the constructor
                            required_bytes=required_bytes_estimate,
                            available_bytes=available_bytes,
                            # Keyword arguments for the base class (**kwargs)
                            context={
                                "key": original_key_to_fetch,
                                "file_size": metadata_size,
                                "bytes_written_to_bundle": bytes_written,
                            },
                        ) from e
                    else:
                        logger.warning(
                            f"OS error while processing file: {e}",
                            extra={
                                "key": original_key_to_fetch,
                                "errno": e.errno,
                                "strerror": e.strerror,
                            },
                        )
                        continue

                except tarfile.TarError as e:
                    raise BundleCreationError(
                        "Failed to add file to tarball",
                        context={"key": original_key_to_fetch},
                    ) from e
                except Exception:
                    logger.exception(
                        "Unexpected error adding file. Skipping.",
                        extra={"key": original_key_to_fetch},
                    )
                    continue

        logger.info(
            f"Finished processing batch. Added {len(processed_records)} records."
        )
        hashing_writer.flush()
        sha256_hash = hashing_writer.hexdigest()
        output_spool_file.seek(0)
        yield cast(BinaryIO, output_spool_file), sha256_hash, processed_records

    finally:
        output_spool_file.close()


# --- High-Level Orchestrator ---
def process_and_stage_batch(
    # --- REFACTOR ---: Expects a list of Pydantic models.
    records: list[S3EventNotificationRecord],
    s3_client: S3Client,
    distribution_bucket: str,
    bundle_key: str,
    context: LambdaContext,
    config: AppConfig,
) -> tuple[str, list[S3EventNotificationRecord], list[S3EventNotificationRecord]]:
    """
    Creates a bundle from pre-validated records, uploads it, and returns the
    hash, processed records, and any remaining (unprocessed) records.
    """
    # The handler guarantees that 'records' is a non-empty list of valid objects
    # and that the other parameters are correct.
    try:
        with create_tar_gz_bundle_stream(s3_client, records, context, config) as (
            bundle,
            sha256_hash,
            processed_records,
        ):
            try:
                s3_client.upload_gzipped_bundle(
                    bucket=distribution_bucket,
                    key=bundle_key,
                    file_obj=bundle,
                    content_hash=sha256_hash,
                )
            except Exception as e:
                raise BundleCreationError(
                    f"Failed to upload bundle to S3: {e}",
                    error_code="BUNDLE_UPLOAD_FAILED",
                ) from e

        logger.info(
            "Successfully staged bundle",
            extra={
                "key": bundle_key,
                "hash": sha256_hash,
                "processed_count": len(processed_records),
            },
        )

        # Calculate remaining records (logic is the same, but works on Pydantic objects)
        processed_set = set(processed_records)
        remaining_records = [r for r in records if r not in processed_set]

        return sha256_hash, processed_records, remaining_records

    except (MemoryLimitError, DiskSpaceError, BundleCreationError):
        # Re-raise our specific, expected exceptions
        raise
    except Exception as e:
        # Wrap any other unexpected errors in a generic batch processing error
        raise BundleCreationError(
            f"Unexpected error during batch processing: {e}",
        ) from e

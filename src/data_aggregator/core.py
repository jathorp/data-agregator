# src/data_aggregator/core.py

import hashlib
import io
import logging
import os
import re
import tarfile
from contextlib import closing, contextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Iterator, List, Tuple, cast

from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import S3Client
from .exceptions import BundlingTimeoutError
from .schemas import S3EventRecord

logger = logging.getLogger(__name__)

# --- Tunables ---
SPOOL_FILE_MAX_SIZE_BYTES: int = 64 * 1024 * 1024  # 64 MiB – spills to /tmp after this
TIMEOUT_GUARD_THRESHOLD_MS: int = 10_000  # Bail out when < 10s remaining


# --- Helpers ---
def _sanitize_s3_key(key: str) -> str | None:
    """Return a safe, relative POSIX path or None if the key is disallowed."""
    try:
        # 1. Strip Windows drive letters first (platform-agnostic).
        key_no_drive = re.sub(r"^[a-zA-Z]:", "", key)

        # 2. Consistently use forward slashes.
        path_with_fwd_slashes = key_no_drive.replace("\\", "/")

        # 3. Check for null bytes before they can cause errors.
        if "\x00" in path_with_fwd_slashes:
            return None

        # 4. Use os.path.normpath to collapse ".." and "." components.
        normalized_path = os.path.normpath(path_with_fwd_slashes)

        # 5. Strip leading slashes to ensure the path is always relative.
        safe_key = normalized_path.lstrip("/")

        # 6. Final checks for traversal attempts or invalid root-like paths.
        if safe_key.startswith("..") or safe_key in {"", "."}:
            return None

        return safe_key
    except TypeError:
        # Catch any other unexpected type errors during processing.
        return None


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
        # Be defensive: In case of weird states, don't flush a closed file.
        if not self._fileobj.closed:
            self._fileobj.flush()

    def close(self) -> None:
        """Prevent tarfile from closing the file, but ensure it's flushed."""
        self.flush()  # Ensure any buffered data is written
        # Do not call self._fileobj.close()

    # Capability flags to satisfy the IOBase interface for type checkers.
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
    records: List[S3EventRecord],
    context: LambdaContext,
) -> Iterator[Tuple[BinaryIO, str]]:
    """
    Stream-creates a compressed tarball from a set of S3 objects.

    Important security note: keys are sanitised to prevent path-traversal
    (Zip-Slip) when the tarball is later extracted.
    """
    spool_file: BinaryIO = SpooledTemporaryFile(  # type: ignore[assignment]
        max_size=SPOOL_FILE_MAX_SIZE_BYTES,
        mode="w+b",
    )
    hashing_writer = HashingFileWrapper(spool_file)

    try:
        logger.debug("Building .tar.gz bundle stream for %d records.", len(records))

        with tarfile.open(
            mode="w:gz",
            fileobj=cast(BinaryIO, hashing_writer),
            format=tarfile.PAX_FORMAT,
        ) as tar:
            for record in records:
                # 1. Timeout Guard
                if context.get_remaining_time_in_millis() < TIMEOUT_GUARD_THRESHOLD_MS:
                    raise BundlingTimeoutError("Timeout threshold reached mid-bundling.")

                original_key = record["s3"]["object"]["key"]

                # 2. Sanitize Key
                safe_key = _sanitize_s3_key(original_key)
                if not safe_key:
                    logger.warning(
                        "Skipping invalid or potentially malicious key.",
                        extra={"original_key": original_key},
                    )
                    continue

                # 3. Fetch stream from S3
                metadata_size = record["s3"]["object"]["size"]
                bucket = record["s3"]["bucket"]["name"]
                stream: BinaryIO = s3_client.get_file_content_stream(bucket, original_key)

                # 4. Buffer stream and verify its size against metadata
                with closing(stream):
                    content_buffer = io.BytesIO(stream.read())

                actual_size = content_buffer.tell()
                if actual_size != metadata_size:
                    logger.warning(
                        "Skipping file due to size mismatch between S3 metadata and content.",
                        extra={"key": original_key, "expected_size": metadata_size, "actual_size": actual_size}
                    )
                    continue

                # 5. Create TarInfo and add the verified file to the archive
                logger.debug("Adding %s (%d bytes) to tar stream", safe_key, actual_size)

                tarinfo = tarfile.TarInfo(name=safe_key)
                tarinfo.size = actual_size  # Use the verified, actual size
                tarinfo.mtime = 0
                tarinfo.uid = tarinfo.gid = 0
                tarinfo.uname = tarinfo.gname = "root"

                content_buffer.seek(0)  # Rewind buffer before reading
                tar.addfile(tarinfo, fileobj=content_buffer)

        # One-pass hash from the wrapper – no second read needed
        sha256_hash: str = hashing_writer.hexdigest()
        logger.info("Bundle hash calculated", extra={"sha256": sha256_hash})

        spool_file.seek(0)
        yield cast(BinaryIO, spool_file), sha256_hash

    finally:
        logger.debug("Closing spooled temporary file.")
        spool_file.close()


# --- High-Level Orchestrator ---
def process_and_stage_batch(
    records: List[S3EventRecord],
    s3_client: S3Client,
    archive_bucket: str,
    distribution_bucket: str,
    archive_key: str,
    context: LambdaContext,
) -> str:
    """Upload the freshly-built bundle once, copy it to the second bucket."""

    if not records:
        logger.warning("process_and_stage_batch called with an empty list of records.")
        raise ValueError("Cannot process an empty batch.")

    with create_tar_gz_bundle_stream(s3_client, records, context) as (
        bundle_file,
        sha256_hash,
    ):
        # Upload to long-term archive first
        s3_client.upload_gzipped_bundle(
            bucket=archive_bucket,
            key=archive_key,
            file_obj=bundle_file,
            content_hash=sha256_hash,
        )

        # Copy to distribution bucket without re-uploading
        s3_client.copy_bundle(
            source_bucket=archive_bucket,
            source_key=archive_key,
            dest_bucket=distribution_bucket,
            dest_key=archive_key,
        )

    logger.info(
        "Successfully staged bundle", extra={"key": archive_key, "hash": sha256_hash}
    )
    return sha256_hash

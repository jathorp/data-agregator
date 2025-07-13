# src/data_aggregator/core.py

import gzip
import hashlib
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Dict, Iterator, List, Tuple, cast

from .clients import S3Client


@contextmanager
def create_gzipped_bundle_stream(
    s3_client: S3Client, records: List[Dict]
) -> Iterator[Tuple[BinaryIO, str]]:
    """
    Creates a Gzip bundle in memory from multiple S3 objects, yielding
    a file-like object and its SHA256 hash.
    """
    # Use a spooled temporary file to buffer in memory and spill to disk if large
    spool_file = SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    hasher = hashlib.sha256()
    try:
        with gzip.GzipFile(fileobj=spool_file, mode="wb") as gz:
            for record in records:
                bucket = record["s3"]["bucket"]["name"]
                key = record["s3"]["object"]["key"]
                header = f"--- BEGIN {key} ---\n".encode("utf-8")
                footer = f"\n--- END {key} ---\n".encode("utf-8")

                with s3_client.get_file_content_stream(
                    bucket=bucket, key=key
                ) as stream:
                    # Write header, stream content, then footer
                    gz.write(header)
                    hasher.update(header)
                    for chunk in stream.iter_chunks(chunk_size=64 * 1024):
                        gz.write(chunk)
                        hasher.update(chunk)
                    gz.write(footer)
                    hasher.update(footer)

        content_hash = hasher.hexdigest()
        spool_file.seek(0) # Rewind the file to the beginning for reading
        yield cast(BinaryIO, spool_file), content_hash
    finally:
        spool_file.close()


def process_and_stage_batch(
    records: List[Dict],
    s3_client: S3Client,
    archive_bucket: str,
    distribution_bucket: str,
    archive_key: str,
) -> str:
    """Orchestrates creating a Gzip bundle and writing it to two S3 locations."""
    if not records:
        raise ValueError("Cannot process an empty batch of records.")

    with create_gzipped_bundle_stream(s3_client, records) as (
        bundle_file,
        content_hash,
    ):
        # 1. Write to the long-term archive bucket
        s3_client.upload_gzipped_bundle(
            bucket=archive_bucket,
            key=archive_key,
            file_obj=bundle_file,
            content_hash=content_hash,
        )

        # Rewind the file stream so it can be read again from the beginning
        bundle_file.seek(0)

        # 2. Write the exact same bundle to the distribution bucket for pickup
        s3_client.upload_gzipped_bundle(
            bucket=distribution_bucket,
            key=archive_key, # Use the same key for consistency
            file_obj=bundle_file,
            content_hash=content_hash,
        )

    return content_hash
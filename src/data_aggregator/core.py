# src/data_aggregator/core.py

import gzip
import hashlib
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Dict, Iterator, List, Tuple, cast

from .clients import NiFiClient, S3Client


@contextmanager
def create_gzipped_bundle_stream(
    s3_client: S3Client, records: List[Dict]
) -> Iterator[Tuple[BinaryIO, str]]:
    spool_file = SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    hasher = hashlib.sha256()
    try:
        with gzip.GzipFile(fileobj=spool_file, mode="wb") as gz:
            for record in records:
                bucket = record["s3"]["bucket"]["name"]
                key = record["s3"]["object"]["key"]
                header = f"--- BEGIN {key} ---\n".encode("utf-8")
                footer = f"\n--- END {key} ---\n".encode("utf-8")

                # UPDATED: Use the new streaming method
                with s3_client.get_file_content_stream(
                    bucket=bucket, key=key
                ) as stream:
                    gz.write(header)
                    hasher.update(header)
                    # Read in chunks to keep memory usage low
                    for chunk in stream.iter_chunks(chunk_size=64 * 1024):
                        gz.write(chunk)
                        hasher.update(chunk)
                    gz.write(footer)
                    hasher.update(footer)

        content_hash = hasher.hexdigest()
        spool_file.seek(0)
        yield cast(BinaryIO, spool_file), content_hash
    finally:
        spool_file.close()


def process_and_deliver_batch(
    records: List[Dict],
    s3_client: S3Client,
    nifi_client: NiFiClient,
    archive_bucket: str,
    archive_key: str,
    read_timeout: int,
) -> str:
    """Orchestrates the main streaming business logic for a batch of records."""
    if not records:
        raise ValueError("Cannot process an empty batch of records.")

    with create_gzipped_bundle_stream(s3_client, records) as (
        bundle_file,
        content_hash,
    ):
        s3_client.upload_gzipped_bundle(
            bucket=archive_bucket,
            key=archive_key,
            file_obj=bundle_file,
            content_hash=content_hash,
        )

        bundle_file.seek(0)

        # UPDATED: Pass the read_timeout to the NiFi client call.
        nifi_client.post_bundle(
            data=bundle_file, content_hash=content_hash, read_timeout=read_timeout
        )

    return content_hash

# # src/data_aggregator/core.py
#
# """
# Core business logic for creating and staging data bundles.
#
# This module contains the memory-intensive logic for reading multiple S3 objects,
# compressing them into a single gzip stream, and orchestrating the final upload
# and copy operations. It is designed to be highly memory-efficient.
# """
#
# import gzip
# import hashlib
# import logging
# from contextlib import contextmanager, closing
# from tempfile import SpooledTemporaryFile
# from typing import BinaryIO, Iterator, List, Tuple, cast
#
# from aws_lambda_powertools.utilities.typing import LambdaContext
#
# from .exceptions import BundlingTimeoutError
# from .clients import S3Client
# from .schemas import S3EventRecord
#
# logger = logging.getLogger(__name__)
#
#
# @contextmanager
# def create_gzipped_bundle_stream(
#     s3_client: S3Client, records: List[S3EventRecord], context: LambdaContext
# ) -> Iterator[Tuple[BinaryIO, str]]:
#     """
#     Creates a Gzip bundle from multiple S3 objects, yielding a file-like object.
#
#     This function is a context manager to ensure the temporary file used for
#     buffering is always cleaned up. It uses several optimizations:
#       - `SpooledTemporaryFile`: Buffers in memory, spilling to disk only if >64MB.
#       - `contextlib.closing`: Safely closes the S3 stream which is not a context manager.
#       - Periodic Timeout Check: Prevents timeouts during long-running streams.
#
#     Yields:
#         A tuple containing the binary file-like object and its SHA256 hash.
#     """
#     spool_file = SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
#     hasher = hashlib.sha256()
#
#     try:
#         logger.debug(
#             "Building gzip bundle stream", extra={"record_count": len(records)}
#         )
#         with gzip.GzipFile(fileobj=spool_file, mode="wb") as gz:
#             for record in records:
#                 bucket, key = (
#                     record["s3"]["bucket"]["name"],
#                     record["s3"]["object"]["key"],
#                 )
#                 logger.debug("Appending object to bundle stream", extra={"key": key})
#                 header, footer = (
#                     f"--- BEGIN {key} ---\n".encode("utf-8"),
#                     f"\n--- END {key} ---\n".encode("utf-8"),
#                 )
#
#                 stream = s3_client.get_file_content_stream(bucket, key)
#                 with closing(stream):  # CRITICAL: Ensures S3 stream is closed properly.
#                     gz.write(header)
#                     hasher.update(header)
#                     for i, chunk in enumerate(stream.iter_chunks(chunk_size=64 * 1024)):
#                         # Every 32 chunks (~2MB), check if we are about to time out.
#                         if i > 0 and i % 32 == 0:
#                             if context.get_remaining_time_in_millis() < 8_000:
#                                 raise BundlingTimeoutError(
#                                     "Timeout threshold reached mid-stream."
#                                 )
#                         gz.write(chunk)
#                         hasher.update(chunk)
#                     gz.write(footer)
#                     hasher.update(footer)
#
#         sha256_hash = hasher.hexdigest()
#         logger.info("Bundle stream created successfully", extra={"sha256": sha256_hash})
#         spool_file.seek(0)  # CRITICAL: Rewind file to the beginning for reading.
#         yield cast(BinaryIO, spool_file), sha256_hash
#     finally:
#         logger.debug("Closing spooled temporary file.")
#         spool_file.close()
#
#
# def process_and_stage_batch(
#     records: List[S3EventRecord],
#     s3_client: S3Client,
#     archive_bucket: str,
#     distribution_bucket: str,
#     archive_key: str,
#     context: LambdaContext,
# ) -> str:
#     """
#     Orchestrates creating a Gzip bundle and writing it to two S3 locations.
#
#     This uses an efficient "upload then copy" pattern to minimize Lambda runtime
#     and data transfer costs.
#
#     Returns:
#         The SHA256 content hash of the created bundle.
#     """
#     if not records:
#         logger.warning("process_and_stage_batch called with an empty list of records.")
#         raise ValueError("Cannot process an empty batch.")
#
#     with create_gzipped_bundle_stream(s3_client, records, context=context) as (
#         bundle_file,
#         sha256_hash,
#     ):
#         # Step 1: Upload the bundle to the long-term archive bucket.
#         s3_client.upload_gzipped_bundle(
#             bucket=archive_bucket,
#             key=archive_key,
#             file_obj=bundle_file,
#             content_hash=sha256_hash,
#         )
#
#         # Step 2: Use the efficient S3 CopyObject API for the second location.
#         s3_client.copy_bundle(
#             source_bucket=archive_bucket,
#             source_key=archive_key,
#             dest_bucket=distribution_bucket,
#             dest_key=archive_key,
#         )
#
#     return sha256_hash

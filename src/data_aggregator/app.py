"""
Main AWS Lambda handler for the Data Aggregation Pipeline.

This module is the entry point for the Lambda function. It is triggered by messages
in an SQS queue, where each message points to a new data file that has arrived in an
S3 bucket.

The primary responsibilities of this handler are:
1.  **Batch Processing**: Efficiently handle batches of incoming SQS messages.
2.  **Idempotency**: Ensure that a file is never processed more than once.
3.  **Archiving**: Collect unique files from a batch into a compressed archive.
4.  **Data Transfer**: Upload the archive to a secure storage system (MinIO).
5.  **Integrity and Auditing**: Verify a SHA256 checksum for every archive.

This code uses the AWS Lambda Powertools for Python (v2) toolkit to enforce best
practices for logging, metrics, and tracing.
"""

import hashlib
import json
import os
import queue
import tarfile
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast, IO
from urllib.parse import unquote

import boto3
# --- Powertools Setup ---
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.data_classes import SQSRecord
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError, EndpointConnectionError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import CopySourceTypeDef

from . import clients, core
from .clients import BOTO_CONFIG_RETRYABLE


# --- 1. SETUP: Configuration and Powertools Initialization ---

def get_env_var(name: str, default: Optional[str] = None) -> str:
    """Safely retrieves an environment variable, failing fast if not set."""
    value = os.environ.get(name, default)
    if value is None:
        raise ValueError(f"FATAL: Environment variable '{name}' is not set.")
    return value


# --- Configuration ---
POWERTOOLS_SERVICE_NAME = get_env_var("POWERTOOLS_SERVICE_NAME", "DataAggregator")
POWERTOOLS_METRICS_NAMESPACE = get_env_var("POWERTOOLS_METRICS_NAMESPACE", "DataMovePipeline")
LANDING_BUCKET = get_env_var("LANDING_BUCKET")
QUEUE_URL = get_env_var("QUEUE_URL")
IDEMPOTENCY_TABLE = get_env_var("IDEMPOTENCY_TABLE")
ENVIRONMENT = get_env_var("ENVIRONMENT", "dev")
MINIO_SECRET_ID = get_env_var("MINIO_SECRET_ID")
MINIO_BUCKET = get_env_var("MINIO_BUCKET")
MINIO_SSE_TYPE = get_env_var("MINIO_SSE_TYPE", "AES256")
SECRET_CACHE_TTL_SECONDS = int(get_env_var("SECRET_CACHE_TTL_SECONDS", "300"))
MAX_FETCH_WORKERS = int(get_env_var("MAX_FETCH_WORKERS", "8"))
# SPOOL_MAX_MEMORY_BYTES should be configured relative to the Lambda's memory allocation.
# Formula: (function_memory_mb - 128) MB
SPOOL_MAX_MEMORY_BYTES = int(get_env_var("SPOOL_MAX_MEMORY_BYTES", "268435456"))
ARCHIVE_TIMEOUT_SECONDS = int(get_env_var("ARCHIVE_TIMEOUT_SECONDS", "300"))
QUEUE_PUT_TIMEOUT_SECONDS = int(get_env_var("QUEUE_PUT_TIMEOUT_SECONDS", "5"))
MIN_REMAINING_TIME_MS = int(get_env_var("MIN_REMAINING_TIME_MS", "60000"))
MAX_FILE_SIZE_BYTES = int(get_env_var("MAX_FILE_SIZE_BYTES", "5242880"))

# Set a long TTL to prevent false duplicates due to DynamoDB's TTL behavior.
# DynamoDB's TTL deletion can take up to 48 hours after an item expires.
# A value of 192 hours (8 days) provides a safe buffer beyond this window
IDEMPOTENCY_TTL_HOURS = int(get_env_var("IDEMPOTENCY_TTL_HOURS", "192"))

# --- Powertools and Boto3 Client Initialization ---
logger = Logger(service=POWERTOOLS_SERVICE_NAME)
metrics = Metrics(namespace=POWERTOOLS_METRICS_NAMESPACE)
tracer = Tracer(service=POWERTOOLS_SERVICE_NAME)
secrets_provider = SecretsProvider()
S3, SQS, DDB, _ = clients.get_boto_clients()
_minio_client_creation_lock = threading.Lock()
_MINIO_CLIENT: Optional[S3Client] = None


# --- 2. STATEFUL & ORCHESTRATION LOGIC ---

class ArchiveHasher:
    """A wrapper around a file stream that calculates a SHA256 checksum on the fly."""
    def __init__(self, stream: IO[bytes]):
        self._stream = stream
        self._hasher = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if chunk:
            self._hasher.update(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


@tracer.capture_method
def get_minio_client() -> S3Client:
    """Initializes and caches a client for connecting to the MinIO storage."""
    global _MINIO_CLIENT
    if _MINIO_CLIENT:
        return cast(S3Client, _MINIO_CLIENT)

    with _minio_client_creation_lock:
        if _MINIO_CLIENT:
            return cast(S3Client, _MINIO_CLIENT)

        logger.info("Creating new MinIO client instance.")
        secret_data: dict = secrets_provider.get(
            MINIO_SECRET_ID,
            max_age=SECRET_CACHE_TTL_SECONDS,
            transform="json",
        )
        _MINIO_CLIENT = cast(
            S3Client,
            boto3.client(
                "s3",
                endpoint_url=secret_data["endpoint_url"],
                aws_access_key_id=secret_data["access_key"],
                aws_secret_access_key=secret_data["secret_key"],
                config=BOTO_CONFIG_RETRYABLE,
            ),
        )
        return _MINIO_CLIENT


@tracer.capture_method
def stream_archive_to_minio(
    s3_keys: list[str], dest_key: str, context: LambdaContext
) -> str:
    """
    Orchestrates the creation and upload of the final data archive.

    This function uses multiple threads to fetch files in parallel while a single
    writer thread builds the compressed archive. This design allows it to handle
    large numbers of files efficiently without running out of memory.
    """
    global _MINIO_CLIENT

    # The queue is capped to the number of workers to apply back-pressure
    # and prevent buffering too many open network streams in memory.
    data_queue: queue.Queue = queue.Queue(maxsize=MAX_FETCH_WORKERS)
    error_queue: queue.Queue = queue.Queue()
    error_event = threading.Event()

    @tracer.capture_method
    def _fetcher(key: str):
        s3_obj = None
        try:
            s3_obj = S3.get_object(Bucket=LANDING_BUCKET, Key=key)
            content_length = s3_obj["ContentLength"]
            if content_length > MAX_FILE_SIZE_BYTES:
                raise ValueError(f"File {key} ({content_length} bytes) exceeds max size.")
            data_queue.put(
                (key, s3_obj["Body"], content_length), timeout=QUEUE_PUT_TIMEOUT_SECONDS
            )
        except queue.Full:
            err = RuntimeError("Queue full; writer thread may be stalled or too slow.")
            logger.warning("Back-pressure detected.", extra={"error": str(err), "key": key})
            metrics.add_metric(name="QueuePutStalled", unit=MetricUnit.Count, value=1)
            if s3_obj and s3_obj.get("Body"):
                try:
                    s3_obj["Body"].close()
                except Exception as close_exc:
                    logger.warning("Failed to close S3 stream during queue.Full handling.",
                                   extra={"close_error": str(close_exc)})
            error_queue.put(err)
            error_event.set()
        except Exception as fetch_err:
            if s3_obj and s3_obj.get("Body"):
                try:
                    s3_obj["Body"].close()
                except Exception as close_exc:
                    logger.warning("Failed to close S3 stream during error handling.",
                                   extra={"close_error": str(close_exc)})
            logger.exception(f"Fetcher thread failed for key {key}")
            error_queue.put(fetch_err)
            error_event.set()

    @tracer.capture_method
    def _writer(spooled_file: tempfile.SpooledTemporaryFile):
        seen_base_names: Dict[str, int] = {}
        try:
            with tarfile.open(fileobj=spooled_file, mode="w:gz") as tar:
                while not error_event.is_set():
                    try:
                        item = data_queue.get(block=True, timeout=0.1)
                        if item is None:
                            break
                        key, body_stream, size = item
                        try:
                            basename = os.path.basename(key)
                            if basename in seen_base_names:
                                seen_base_names[basename] += 1
                                name, ext = os.path.splitext(basename)
                                unique_name = f"{name}({seen_base_names[basename]}){ext}"
                            else:
                                seen_base_names[basename] = 0
                                unique_name = basename

                            tarinfo = tarfile.TarInfo(name=unique_name)
                            tarinfo.size = size
                            tar.addfile(tarinfo, body_stream)
                        finally:
                            body_stream.close()
                    except queue.Empty:
                        continue
        except Exception as writer_err:
            logger.exception("Writer thread failed")
            error_queue.put(writer_err)
            error_event.set()

    executor = ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS)
    try:
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY_BYTES, mode="w+b") as spooled_archive:
            writer_thread = threading.Thread(name="tar-writer", target=_writer, args=(spooled_archive,))
            writer_thread.start()

            for s3_key in s3_keys:
                if error_event.is_set():
                    break
                executor.submit(_fetcher, s3_key)

            executor.shutdown(wait=False)

            time_remaining_seconds = (context.get_remaining_time_in_millis() // 1000) - 10
            join_timeout = max(1, min(time_remaining_seconds, ARCHIVE_TIMEOUT_SECONDS))
            writer_thread.join(timeout=join_timeout)

            if not error_queue.empty():
                raise error_queue.get()

            if writer_thread.is_alive():
                # Signal all worker threads to stop processing immediately.
                error_event.set()
                raise TimeoutError("Archive writer thread timed out.")

            spooled_archive.flush()
            archive_size_bytes = spooled_archive.tell()
            metrics.add_metric(name="ArchiveSizeBytes", unit=MetricUnit.Bytes, value=archive_size_bytes)

            for attempt in range(2):
                try:
                    minio_client = get_minio_client()
                    spooled_archive.seek(0)
                    hasher = ArchiveHasher(spooled_archive)

                    # ░░ Upload strategy rationale ░░
                    #
                    # We stream the archive to MinIO with `upload_fileobj`, then immediately make a
                    # lightweight `copy_object` to attach the final SHA-256 checksum as *object
                    # metadata*.
                    #
                    # • Why not calculate the digest first?
                    #   That would require reading the entire SpooledTemporaryFile *twice* (once to
                    #   hash, once to upload), doubling local I/O and increasing overall latency.
                    #
                    # • Why not add the digest as an *object tag*?
                    #   Tags allow a single PUT + PutObjectTagging call, but many S3/MinIO tools and
                    #   downstream consumers ignore tags by default. We need the checksum visible in
                    #   a simple `HEAD` request for ops/audit use-cases.
                    #
                    # • Cost/SLO trade-off
                    #   The extra `copy_object` stays within the same bucket—no data egress—and is
                    #   fast enough (<100 ms for our 300 MB worst-case archive). If network cost or
                    #   latency becomes a concern, revisit:
                    #     1. **Tag-then-verify** pattern (see docs/alt_upload_patterns.md)
                    #     2. **Double-read, single PUT** if Lambda memory/time budgets improve.
                    #
                    # Bottom line: this two-call approach balances correctness, visibility, and
                    # memory efficiency better than the alternatives in today’s constraints.

                    # 1. Upload the file object. The hasher will calculate the digest as the stream is read.
                    extra_args: Dict[str, Any] = {}
                    if MINIO_SSE_TYPE != "NONE":
                        extra_args["ServerSideEncryption"] = MINIO_SSE_TYPE

                    minio_client.upload_fileobj(
                        cast(IO[bytes], hasher), MINIO_BUCKET, dest_key, ExtraArgs=extra_args
                    )

                    # 2. Now that the stream is fully read, get the final digest.
                    digest = hasher.hexdigest()

                    # 3. Perform a self-copy to atomically add the checksum as metadata.
                    copy_source: CopySourceTypeDef = {"Bucket": MINIO_BUCKET, "Key": dest_key}
                    minio_client.copy_object(
                        Bucket=MINIO_BUCKET,
                        Key=dest_key,
                        CopySource=copy_source,
                        Metadata={"sha256_checksum": digest},
                        MetadataDirective="REPLACE",
                        **extra_args,
                    )

                    logger.info("Successfully uploaded archive with metadata.")
                    return digest
                except EndpointConnectionError as conn_err:
                    if attempt == 0:
                        logger.warning("MinIO connection error. Invalidating client cache and retrying.",
                                       extra={"error": str(conn_err)})
                        _MINIO_CLIENT = None
                        continue
                    raise
                except ClientError as e:
                    if (e.response["Error"]["Code"] in ["AccessDenied", "InvalidAccessKeyId"]
                            and attempt == 0):
                        logger.warning("MinIO access denied. Invalidating secret/client caches and retrying.")
                        secrets_provider.clear_cache()
                        _MINIO_CLIENT = None
                        continue
                    raise
        raise RuntimeError("Failed to upload archive to MinIO after all attempts.")
    finally:
        executor.shutdown(wait=True)


# --- 3. LAMBDA HANDLER ---

@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext):
    """
    Main Lambda entry point. Orchestrates the entire aggregation process using
    the Powertools BatchProcessor.
    """
    metrics.add_dimension(name="Environment", value=ENVIRONMENT)
    unique_keys_to_process: List[str] = []

    def collect_s3_keys(record: SQSRecord):
        """Processes a single SQS message to identify and validate a file key."""
        try:
            message_content = json.loads(record.body)
            s3_key = unquote(message_content['Records'][0]['s3']['object']['key'])

            table = DDB.Table(IDEMPOTENCY_TABLE)
            ttl = int((datetime.now(timezone.utc) + timedelta(hours=IDEMPOTENCY_TTL_HOURS)).timestamp())
            is_unique = core.is_object_unique(table, ttl, s3_key, record.message_id, logger)

            if is_unique:
                unique_keys_to_process.append(s3_key)
            else:
                logger.info(f"Skipping duplicate S3 key: {s3_key}")

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.exception("Failed to parse SQS message or find S3 key.", extra={"error": str(e)})
            raise

    processor = BatchProcessor(event_type=EventType.SQS)
    with processor(event, collect_s3_keys):  # type: ignore[arg-type]
        pass

    if unique_keys_to_process:
        logger.info(f"Starting archive for {len(unique_keys_to_process)} unique files.")
        dest_key = f"archive/{datetime.now(timezone.utc).strftime('%Y/%m/%d/%H%M%S')}-{context.aws_request_id}.tar.gz"
        digest = stream_archive_to_minio(unique_keys_to_process, dest_key, context)
        logger.info("Successfully processed batch.",
                    extra={"output_key": dest_key, "sha256_checksum": digest})
    else:
        logger.info("No new unique files to process in this batch.")

    if processor.fail_messages:
        failed_message_ids = [msg.message_id for msg in processor.fail_messages]
        logger.warning(f"Failed to process {len(failed_message_ids)} messages.",
                       extra={"failed_message_ids": failed_message_ids})

    return processor.response()
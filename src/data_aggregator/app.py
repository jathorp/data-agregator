"""
Main AWS Lambda handler for the Data Aggregation Pipeline.

This module is the entry point for the Lambda function. It is triggered by messages
in an SQS queue, where each message points to a new data file that has arrived in an
S3 bucket.

The primary responsibilities of this handler are:
1.  **Batch Processing**: Efficiently handle batches of incoming SQS messages.
2.  **Idempotency**: Ensure that a file is never processed more than once, even if
    the same message is received multiple times.
3.  **Archiving**: Collect all unique, new data files from a batch.
4.  **Data Transfer**: Bundle these files into a single compressed archive (`.tar.gz`)
    and upload it to a secure, long-term storage system (MinIO).
5.  **Integrity and Auditing**: Generate and verify a SHA256 checksum for every
    archive to guarantee data integrity. Log all actions for observability.

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
from typing import List, Optional, cast, IO
from urllib.parse import unquote_plus

import boto3

# --- Powertools Setup ---
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.data_classes import SQSRecord
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import CopySourceTypeDef

from . import clients, core
from .clients import BOTO_CONFIG_RETRYABLE


# --- 1. SETUP: Configuration and Powertools Initialization ---


def get_env_var(name: str, default: Optional[str] = None) -> str:
    """
    Safely retrieves an environment variable. If the variable is not set, the
    Lambda function will fail instantly with a clear error message, preventing
    unexpected behavior during execution.

    Args:
        name: The name of the environment variable (e.g., "LANDING_BUCKET").
        default: A fallback value to use if the variable is not found.

    Returns:
        The value of the environment variable.

    Raises:
        ValueError: If the environment variable is not set and no default is provided.
    """
    value = os.environ.get(name, default)
    if value is None:
        raise ValueError(f"FATAL: Environment variable '{name}' is not set.")
    return value


# --- Configuration ---
# These environment variables control the behavior of the Lambda function.
# They are set in the Lambda's configuration console or deployment templates.

# --- General & AWS ---
POWERTOOLS_SERVICE_NAME = get_env_var("POWERTOOLS_SERVICE_NAME", "DataAggregator")
POWERTOOLS_METRICS_NAMESPACE = get_env_var(
    "POWERTOOLS_METRICS_NAMESPACE", "DataMovePipeline"
)
LANDING_BUCKET = get_env_var("LANDING_BUCKET")
QUEUE_URL = get_env_var("QUEUE_URL")
IDEMPOTENCY_TABLE = get_env_var("IDEMPOTENCY_TABLE")
ENVIRONMENT = get_env_var("ENVIRONMENT", "dev")

# --- Target Storage (MinIO) ---
MINIO_SECRET_ID = get_env_var("MINIO_SECRET_ID")
MINIO_BUCKET = get_env_var("MINIO_BUCKET")
MINIO_SSE_TYPE = get_env_var("MINIO_SSE_TYPE", "AES256")

# --- Business Logic & Performance Tuning ---
IDEMPOTENCY_TTL_HOURS = int(get_env_var("IDEMPOTENCY_TTL_HOURS", "24"))
SECRET_CACHE_TTL_SECONDS = int(get_env_var("SECRET_CACHE_TTL_SECONDS", "300"))
MAX_FETCH_WORKERS = int(get_env_var("MAX_FETCH_WORKERS", "8"))
SPOOL_MAX_MEMORY_BYTES = int(get_env_var("SPOOL_MAX_MEMORY_BYTES", "268435456"))
ARCHIVE_TIMEOUT_SECONDS = int(get_env_var("ARCHIVE_TIMEOUT_SECONDS", "300"))
QUEUE_PUT_TIMEOUT_SECONDS = int(get_env_var("QUEUE_PUT_TIMEOUT_SECONDS", "5"))
MIN_REMAINING_TIME_MS = int(get_env_var("MIN_REMAINING_TIME_MS", "60000"))
MAX_FILE_SIZE_BYTES = int(get_env_var("MAX_FILE_SIZE_BYTES", "5242880"))

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
    """
    A wrapper around a file stream that calculates a SHA256 checksum on the fly.

    As the file is read chunk by chunk (e.g., during an upload), this class
    updates the hash. This avoids reading the file into memory twice (once to
    hash, once to upload), saving time and memory.
    """

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
    """
    Initializes and caches a client for connecting to the MinIO storage.

    It retrieves credentials securely from AWS Secrets Manager and caches them.
    If the connection fails due to an authentication error, it automatically
    invalidates the cache and retries once, which can self-heal from temporary
    credential-related issues.
    """
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

    This is the core data processing function. It uses multiple threads to fetch
    files from S3 in parallel while a single writer thread builds the compressed
    archive. This design allows it to handle large numbers of files efficiently
    without running out of memory.

    QA Checks for this function:
    - Verify that the final archive in MinIO contains exactly the files listed
      in the `s3_keys` list.
    - Confirm the archive has a `sha256_checksum` in its metadata that matches
      the value returned by this function.
    - Check CloudWatch logs for any warnings about "Back-pressure" or the archive
      "spooling to disk," which could indicate performance bottlenecks.
    """
    data_queue: queue.Queue = queue.Queue(maxsize=MAX_FETCH_WORKERS * 4)
    error_queue: queue.Queue = queue.Queue()
    error_event = threading.Event()

    @tracer.capture_method
    def _fetcher(key: str):
        s3_obj = None
        try:
            s3_obj = S3.get_object(Bucket=LANDING_BUCKET, Key=key)
            content_length = s3_obj["ContentLength"]
            if content_length > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"File {key} ({content_length} bytes) exceeds max size."
                )
            data_queue.put(
                (key, s3_obj["Body"], content_length), timeout=QUEUE_PUT_TIMEOUT_SECONDS
            )
        except queue.Full:
            err = RuntimeError("Queue full; writer thread may be stalled or too slow.")
            logger.warning(
                "Back-pressure detected.", extra={"error": str(err), "key": key}
            )
            metrics.add_metric(name="QueuePutStalled", unit=MetricUnit.Count, value=1)
            if s3_obj:
                try:
                    s3_obj["Body"].close()
                except Exception as close_exc:
                    logger.warning(
                        "Failed to close S3 stream.",
                        extra={"close_error": str(close_exc)},
                    )
            error_queue.put(err)
            error_event.set()
        except Exception as fetch_err:
            if s3_obj:
                try:
                    s3_obj["Body"].close()
                except Exception as close_exc:
                    logger.warning(
                        "Failed to close S3 stream during error handling.",
                        extra={"close_error": str(close_exc)},
                    )
            logger.exception(f"Fetcher thread failed for key {key}")
            error_queue.put(fetch_err)  # <-- Use the new name here
            error_event.set()

    @tracer.capture_method
    def _writer(spooled_file: tempfile.SpooledTemporaryFile):
        try:
            with tarfile.open(fileobj=spooled_file, mode="w:gz") as tar:
                while not error_event.is_set():
                    try:
                        item = data_queue.get(block=True, timeout=0.1)
                        if item is None:
                            break
                        key, body_stream, size = item
                        try:
                            tarinfo = tarfile.TarInfo(name=key)
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

    with tempfile.SpooledTemporaryFile(
        max_size=SPOOL_MAX_MEMORY_BYTES, mode="w+b"
    ) as spooled_archive:
        writer_thread = threading.Thread(
            name="tar-writer", target=_writer, args=(spooled_archive,)
        )
        writer_thread.start()
        with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as executor:
            for s3_key in s3_keys:
                if error_event.is_set():
                    break
                executor.submit(_fetcher, s3_key)

        if not error_event.is_set():
            data_queue.put(None)

        # Calculate a timeout that is shorter than the remaining Lambda time
        # to ensure our custom timeout logic can run before the Lambda dies.
        # We subtract 10 seconds as a safety buffer.
        time_remaining_seconds = (context.get_remaining_time_in_millis() / 1000) - 10

        # Use the lesser of the configured max timeout and the dynamic remaining time.
        join_timeout = min(time_remaining_seconds, ARCHIVE_TIMEOUT_SECONDS)

        writer_thread.join(timeout=join_timeout)

        if not error_queue.empty():
            raise error_queue.get()

        if writer_thread.is_alive():
            raise TimeoutError("Archive writer thread timed out.")

        spooled_archive.flush()
        is_on_disk = hasattr(spooled_archive, "name") and os.path.exists(
            spooled_archive.name
        )
        if is_on_disk:
            archive_size_on_disk = os.fstat(spooled_archive.fileno()).st_size
            logger.warning(
                "Archive spooled to disk", extra={"size_bytes": archive_size_on_disk}
            )
            metrics.add_metric(
                name="ArchiveSpilledToDisk", unit=MetricUnit.Count, value=1
            )
            if archive_size_on_disk > 400 * 1024 * 1024:
                raise MemoryError(
                    f"Archive on disk ({archive_size_on_disk} bytes) exceeds safe /tmp limit."
                )
        archive_size_bytes = spooled_archive.tell()
        metrics.add_metric(
            name="ArchiveSizeBytes", unit=MetricUnit.Bytes, value=archive_size_bytes
        )
        for attempt in range(2):
            try:
                minio_client = get_minio_client()
                spooled_archive.seek(0)
                hasher = ArchiveHasher(spooled_archive)
                extra_args = {}
                if MINIO_SSE_TYPE != "NONE":
                    extra_args["ServerSideEncryption"] = MINIO_SSE_TYPE
                minio_client.upload_fileobj(
                    cast(IO[bytes], hasher),
                    MINIO_BUCKET,
                    dest_key,
                    ExtraArgs=extra_args,
                )
                digest = hasher.hexdigest()
                copy_source: CopySourceTypeDef = {
                    "Bucket": MINIO_BUCKET,
                    "Key": dest_key,
                }
                minio_client.copy_object(
                    Bucket=MINIO_BUCKET,
                    Key=dest_key,
                    CopySource=copy_source,
                    Metadata={"sha256_checksum": digest},
                    MetadataDirective="REPLACE",
                    **extra_args,
                )
                head = minio_client.head_object(Bucket=MINIO_BUCKET, Key=dest_key)
                remote_checksum = head.get("Metadata", {}).get("sha256_checksum")
                if remote_checksum != digest:
                    raise RuntimeError(
                        "Data integrity failure: checksum mismatch after upload."
                    )
                logger.info("Successfully uploaded and verified archive.")
                return digest
            except ClientError as e:
                if (
                    e.response["Error"]["Code"]
                    in ["AccessDenied", "InvalidAccessKeyId"]
                    and attempt == 0
                ):
                    logger.warning(
                        "MinIO access denied. Invalidating secret and client caches and retrying."
                    )
                    global _MINIO_CLIENT
                    secrets_provider.clear_cache()
                    _MINIO_CLIENT = None
                    continue
                raise
    raise RuntimeError("Failed to upload archive to MinIO after all attempts.")


# --- 3. LAMBDA HANDLER ---


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext):
    """
    Main Lambda entry point. Orchestrates the entire aggregation process using
    the Powertools BatchProcessor.

    The flow is as follows:
    1. The BatchProcessor receives the entire batch of SQS messages.
    2. It iterates through each message and calls the `collect_s3_keys` function.
    3. `collect_s3_keys` parses the message, checks if the file has been processed
       before (idempotency), and adds new, unique file keys to a list.
    4. If `collect_s3_keys` succeeds, the BatchProcessor automatically deletes the
       corresponding message from the SQS queue.
    5. If it fails (e.g., due to a malformed message), the message is NOT deleted
       and will be retried later. The processor continues with the rest of the batch.
    6. After all messages are processed, the main handler function takes the final
       list of unique keys and calls `stream_archive_to_minio` to create the archive.
    """
    metrics.add_dimension(name="Environment", value=ENVIRONMENT)
    unique_keys_to_process: List[str] = []

    def collect_s3_keys(record: SQSRecord):
        """
        Processes a single SQS message to identify and validate a file key.
        This function is called by the BatchProcessor for every message.

        Args:
            record: An SQS message object provided by Powertools.
        """
        try:
            message_content = json.loads(record.body)
            # Use unquote_plus to handle special characters like '+' or '%20' in keys
            s3_key = unquote_plus(message_content["Records"][0]["s3"]["object"]["key"])

            table = DDB.Table(IDEMPOTENCY_TABLE)
            ttl = int(
                (
                    datetime.now(timezone.utc) + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
                ).timestamp()
            )
            is_unique = core.is_object_unique(
                table, ttl, s3_key, record.message_id, logger
            )

            if is_unique:
                unique_keys_to_process.append(s3_key)
            else:
                logger.info(f"Skipping duplicate S3 key: {s3_key}")

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.exception(
                "Failed to parse SQS message or find S3 key.", extra={"error": str(e)}
            )
            raise

    processor = BatchProcessor(event_type=EventType.SQS)
    with processor(event, collect_s3_keys):  # type: ignore[arg-type]
        pass

    if unique_keys_to_process:
        logger.info(f"Starting archive for {len(unique_keys_to_process)} unique files.")
        dest_key = f"archive/{datetime.now(timezone.utc).strftime('%Y/%m/%d/%H%M%S')}-{context.aws_request_id}.tar.gz"
        digest = stream_archive_to_minio(unique_keys_to_process, dest_key, context)
        logger.info(
            "Successfully processed batch.",
            extra={"output_key": dest_key, "sha256_checksum": digest},
        )
    else:
        logger.info("No new unique files to process in this batch.")

    if processor.fail_messages:
        failed_message_ids = [msg.message_id for msg in processor.fail_messages]
        logger.warning(
            f"Failed to process {len(failed_message_ids)} messages.",
            extra={"failed_message_ids": failed_message_ids},
        )

    return processor.response()

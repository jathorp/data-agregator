# src/data_aggregator/app.py

"""
Main Lambda handler and orchestration logic for the Data Aggregator service.

This function is triggered by SQS and performs the following orchestration:
  1. Securely loads and validates configuration from environment variables.
  2. Processes a batch of SQS messages, each containing an S3 event notification.
  3. For each message, it performs an idempotency check using a hashed key in
     DynamoDB to prevent duplicate processing and hot partitions.
  4. Pre-validates the entire batch against configurable size and time limits.
  5. If valid, it invokes the core logic to create a compressed gzip bundle.
  6. Manages partial failure responses to SQS, ensuring failed messages are retried.
  7. Emits detailed logs, metrics, and traces for robust observability.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, List, cast
from urllib.parse import unquote_plus

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailureResponse,
    PartialItemFailures,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

from .clients import DynamoDBClient, S3Client
from .core import process_and_stage_batch
from .schemas import S3EventRecord
from .exceptions import (
    SQSBatchProcessingError,
    BundlingTimeoutError,
    BatchTooLargeError,
    TransientDynamoError,
)


# ─────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class EnvConfig:
    """
    A strongly-typed, immutable wrapper for all environment variables.

    This class provides a "fail-fast" pattern: if a required environment
    variable is missing, the Lambda will fail during initialization (cold start)
    rather than unpredictably at runtime. This makes deployment errors
    immediately obvious.
    """
    # Required variables
    idempotency_table: str = os.environ["IDEMPOTENCY_TABLE_NAME"]
    archive_bucket: str = os.environ["ARCHIVE_BUCKET_NAME"]
    distribution_bucket: str = os.environ["DISTRIBUTION_BUCKET_NAME"]

    # Optional variables with sensible defaults
    idempotency_ttl_days: int = int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7"))
    dynamodb_ttl_attribute: str = os.environ.get("DYNAMODB_TTL_ATTRIBUTE", "ttl")
    environment: str = os.environ.get("ENV", "dev")
    log_level: str = os.environ.get("POWERTOOLS_LOG_LEVEL", "INFO")
    bundle_kms_key_id: str | None = os.environ.get("BUNDLE_KMS_KEY_ID")
    max_bundle_input_mb: int = int(os.environ.get("MAX_BUNDLE_INPUT_MB", "100"))

    @property
    def idempotency_ttl_seconds(self) -> int:
        return self.idempotency_ttl_days * 86_400

    @property
    def max_bundle_input_bytes(self) -> int:
        return self.max_bundle_input_mb * 1024 * 1024


# Instantiate config once at import time to trigger the fail-fast check.
CONFIG = EnvConfig()

# ─────────────────────────────────────────────────────────────
#  Observability Primitives
# ─────────────────────────────────────────────────────────────
logger = Logger(service="data-aggregator", level=CONFIG.log_level, log_uncaught_exceptions=True)
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")
metrics.set_default_dimensions(environment=CONFIG.environment)

# Boto3 clients are initialized once per container for performance.
_S3 = boto3.client("s3")
_DYNAMODB = boto3.client("dynamodb")

# ─────────────────────────────────────────────────────────────
#  Dependency Container
# ─────────────────────────────────────────────────────────────
class Dependencies:
    """
    A lazy, per-invocation dependency service locator.

    This pattern uses @cached_property to ensure that client wrappers are
    initialized only once per Lambda invocation, improving performance on
    warm starts.
    """

    @cached_property
    def s3_client(self) -> S3Client:
        logger.debug("Initializing S3Client wrapper")
        return S3Client(s3_client=_S3, kms_key_id=CONFIG.bundle_kms_key_id)

    @cached_property
    def dynamodb_client(self) -> DynamoDBClient:
        logger.debug("Initializing DynamoDBClient wrapper")
        return DynamoDBClient(
            dynamo_client=_DYNAMODB,
            table_name=CONFIG.idempotency_table,
            ttl_attribute=CONFIG.dynamodb_ttl_attribute,
        )


# ─────────────────────────────────────────────────────────────
#  Record-Level Handler
# ─────────────────────────────────────────────────────────────
def make_record_handler(deps: Dependencies):
    """
    Factory that returns a configured handler for a single SQS record.

    This higher-order function pattern allows the record handler to access
    invocation-specific dependencies without using globals.
    """

    @tracer.capture_method
    def record_handler(record: SQSRecord) -> S3EventRecord | Dict:
        """
        Processes one SQS record: parses it and checks for idempotency.

        Args:
            record: An SQS record from the batch.

        Raises:
            ValueError: For malformed SQS messages that should go to the DLQ.
            TransientDynamoError: For transient DB errors that should trigger a retry.

        Returns:
            The parsed S3EventRecord if it's new, or an empty dict if it's a duplicate.
        """
        logger.debug("Processing individual SQS record", extra={"message_id": record.message_id})
        try:
            body: Dict[str, Any] = json.loads(record.body)
            s3_record: S3EventRecord = cast(S3EventRecord, body["Records"][0])
            object_key = unquote_plus(s3_record["s3"]["object"]["key"])
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Malformed SQS message – sending to DLQ", extra={"body": record.body})
            raise ValueError("Malformed SQS message") from exc

        idempotency_key_hash = hashlib.sha256(object_key.encode('utf-8')).hexdigest()
        logger.debug("Calculated idempotency hash", extra={"key": object_key, "hash": idempotency_key_hash})

        expiry_ts = int(time.time()) + CONFIG.idempotency_ttl_seconds
        try:
            is_new = deps.dynamodb_client.check_and_set_idempotency(
                idempotency_key=idempotency_key_hash,
                original_object_key=object_key,
                ttl=expiry_ts
            )
        except ClientError as exc:
            logger.exception("DynamoDB error during idempotency check, retrying batch")
            raise TransientDynamoError("DynamoDB client error") from exc

        if not is_new:
            metrics.add_metric(name="DuplicatesSkipped", unit=MetricUnit.Count, value=1)
            logger.info("Duplicate key skipped", extra={"key": object_key})
            return {}

        metrics.add_metric(name="NewObjectsProcessed", unit=MetricUnit.Count, value=1)
        return s3_record

    return record_handler


# ─────────────────────────────────────────────────────────────
#  Batch-Level Processing
# ─────────────────────────────────────────────────────────────
@tracer.capture_method
def _process_successful_batch(
        successful_records: List[Any],
        context: LambdaContext,
        deps: Dependencies,
) -> None:
    """
    Orchestrates bundling and staging for a batch of validated S3 records.

    Performs pre-flight checks for batch size and remaining time before
    initiating the core bundling logic.

    Args:
        successful_records: Records that passed the idempotency check.
        context: The Lambda runtime context object.
        deps: The dependency container.

    Raises:
        BatchTooLargeError: If the total input size exceeds the configured limit.
        BundlingTimeoutError: If there is not enough time left for bundling.
    """
    s3_records: List[S3EventRecord] = successful_records
    logger.debug("Starting stage-2 processing for successful batch", extra={"record_count": len(s3_records)})

    total_input_bytes = sum(record["s3"]["object"]["size"] for record in s3_records)
    if total_input_bytes > CONFIG.max_bundle_input_bytes:
        logger.error("Input batch size exceeds configured limit, requesting retry.",
                     extra={"total_bytes": total_input_bytes, "limit_bytes": CONFIG.max_bundle_input_bytes})
        raise BatchTooLargeError(f"Total input size {total_input_bytes} bytes exceeds limit.")

    if context.get_remaining_time_in_millis() < 8_000:
        raise BundlingTimeoutError(f"Only {context.get_remaining_time_in_millis()} ms remaining.")

    archive_key = f"bundle-{context.aws_request_id}.gz"
    logger.info("Creating bundle", extra={"key": archive_key, "record_count": len(s3_records)})

    with tracer.provider.in_subsegment("process_and_stage_bundle_subsegment"):
        process_and_stage_batch(
            records=s3_records,
            s3_client=deps.s3_client,
            archive_bucket=CONFIG.archive_bucket,
            distribution_bucket=CONFIG.distribution_bucket,
            archive_key=archive_key,
            context=context,
        )

    logger.info("Bundle created and staged successfully", extra={"bundle_key": archive_key})
    metrics.add_metric(name="BundlesCreated", unit=MetricUnit.Count, value=1)
    metrics.add_metric(name="RecordsInBundle", unit=MetricUnit.Count, value=len(s3_records))


# ─────────────────────────────────────────────────────────────
#  Lambda Entrypoint
# ─────────────────────────────────────────────────────────────
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    """
    Main Lambda entry point.

    Orchestrates the SQS batch processing, including individual record validation
    and batch-level bundling, while correctly handling partial failures.
    """
    if "Records" not in event or not event["Records"]:
        logger.warning("Event contains no records, exiting.", extra={"event": event})
        return {"batchItemFailures": []}

    deps = Dependencies()
    processor = BatchProcessor(event_type=EventType.SQS)
    record_handler_func = make_record_handler(deps)

    logger.debug("Starting record-level processing via BatchProcessor")
    with processor(records=event["Records"], handler=record_handler_func):
        processor.process()

    batch_failures: List[PartialItemFailures] = processor.response()["batchItemFailures"]

    # CORRECT: Extract the .result from each successful message object.
    # The .result attribute holds the return value from our record_handler.
    # Also, filter out any None/empty results, which represent duplicates.
    logger.info(f"Batch failed records: {processor.success_messages}")

    successful_records = [rec.result for rec in processor.success_messages if rec.result]

    logger.debug(
        "Record-level processing complete",
        extra={"success_count": len(successful_records), "failure_count": len(batch_failures)},
    )

    if successful_records:
        try:
            # Pass the clean list of S3EventRecord dictionaries to the next function.
            _process_successful_batch(successful_records, context, deps)
        except SQSBatchProcessingError:
            logger.error("Stage-2 bundling failed for a retryable reason. Returning successful items for retry.",
                         exc_info=True)
            # This logic also needs to be updated to reference the message objects.
            for rec in processor.success_messages:
                if rec.result:  # Only retry records that were actually successful in stage 1
                    batch_failures.append({"itemIdentifier": rec.message_id})
    # --- END OF CORRECTED SECTION ---

    if not successful_records and not batch_failures:
        logger.info("All records in batch were duplicates, no new work performed.")
        metrics.add_metric(name="DuplicateOnlyBatch", unit=MetricUnit.Count, value=1)

    logger.info("Batch processing finished", extra={"final_failure_count": len(batch_failures)})
    return {"batchItemFailures": batch_failures}
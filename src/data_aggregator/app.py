# src/data_aggregator/app.py — side‑car‑list variant (simpler “no‑raise” BatchProcessor)
"""
Lambda entry point for the Data‑Aggregator service (SQS → S3 bundler)
---------------------------------------------------------------------
Key design choices
==================
* **Side‑car lists** collect per‑record state; we never mutate Powertools
  objects. This keeps us library‑agnostic and easy to reason about.
* **BatchProcessor(raise_on_entire_batch_failure=False)** – Powertools will now
  *always* populate `processor.response()` instead of throwing
  `BatchProcessingError`. That means we no longer need the `try/except` guard
  nor the manual translation of `failed_messages`.
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
from .exceptions import (
    SQSBatchProcessingError,
    BatchTooLargeError,
    BundlingTimeoutError,
    TransientDynamoError,
)
from .schemas import S3EventRecord

# ─────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class EnvConfig:
    """Fail‑fast wrapper around environment variables."""

    idempotency_table: str = os.environ["IDEMPOTENCY_TABLE_NAME"]
    archive_bucket: str = os.environ["ARCHIVE_BUCKET_NAME"]
    distribution_bucket: str = os.environ["DISTRIBUTION_BUCKET_NAME"]

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


CONFIG = EnvConfig()

# ─────────────────────────────────────────────────────────────
#  Observability primitives
# ─────────────────────────────────────────────────────────────
logger = Logger(service="data-aggregator", level=CONFIG.log_level, log_uncaught_exceptions=True)
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")
metrics.set_default_dimensions(environment=CONFIG.environment)

_S3 = boto3.client("s3")
_DYNAMODB = boto3.client("dynamodb")

# ─────────────────────────────────────────────────────────────
#  Dependency container
# ─────────────────────────────────────────────────────────────
class Dependencies:
    """Per‑invocation lazy clients."""

    @cached_property
    def s3_client(self) -> S3Client:
        return S3Client(s3_client=_S3, kms_key_id=CONFIG.bundle_kms_key_id)

    @cached_property
    def dynamodb_client(self) -> DynamoDBClient:
        return DynamoDBClient(
            dynamo_client=_DYNAMODB,
            table_name=CONFIG.idempotency_table,
            ttl_attribute=CONFIG.dynamodb_ttl_attribute,
        )

# ─────────────────────────────────────────────────────────────
#  Stage‑2 bundling helper
# ─────────────────────────────────────────────────────────────
@tracer.capture_method
def _process_successful_batch(
    successful_records: List[S3EventRecord],
    context: LambdaContext,
    deps: Dependencies,
) -> None:
    """Run pre‑flight checks then call `process_and_stage_batch`."""
    logger.debug("Stage‑2 processing", extra={"record_count": len(successful_records)})

    total_input = sum(r["s3"]["object"]["size"] for r in successful_records)
    if total_input > CONFIG.max_bundle_input_bytes:
        raise BatchTooLargeError(f"Batch is {total_input} bytes > limit")

    if context.get_remaining_time_in_millis() < 8_000:
        raise BundlingTimeoutError("Not enough time left to bundle")

    archive_key = f"bundle-{context.aws_request_id}.gz"

    with tracer.provider.in_subsegment("process_and_stage_bundle_subsegment"):
        process_and_stage_batch(
            records=successful_records,
            s3_client=deps.s3_client,
            archive_bucket=CONFIG.archive_bucket,
            distribution_bucket=CONFIG.distribution_bucket,
            archive_key=archive_key,
            context=context,
        )

    metrics.add_metric("BundlesCreated", MetricUnit.Count, 1)
    metrics.add_metric("RecordsInBundle", MetricUnit.Count, len(successful_records))
    logger.info("Bundle staged", extra={"key": archive_key})

# ─────────────────────────────────────────────────────────────
#  Lambda entry point
# ─────────────────────────────────────────────────────────────
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    """Main Lambda handler (SQS batch)."""
    if not event.get("Records"):
        logger.info("No records, nothing to do")
        return {"batchItemFailures": []}

    deps = Dependencies()

    # Side‑car collectors for stage‑2
    successful_records: list[S3EventRecord] = []
    processed_message_ids: list[str] = []

    # -----------------------------------------------------
    # Inner record handler
    # -----------------------------------------------------
    def record_handler(record: SQSRecord) -> Dict | S3EventRecord:
        try:
            body = json.loads(record.body)
            s3_record: S3EventRecord = cast(S3EventRecord, body["Records"][0])
            object_key = unquote_plus(s3_record["s3"]["object"]["key"])
        except (json.JSONDecodeError, KeyError, IndexError):
            logger.warning("Malformed SQS message", extra={"body": record.body})
            raise ValueError("Malformed SQS message")

        hash_key = hashlib.sha256(object_key.encode()).hexdigest()
        expiry = int(time.time()) + CONFIG.idempotency_ttl_seconds

        try:
            is_new = deps.dynamodb_client.check_and_set_idempotency(
                idempotency_key=hash_key,
                original_object_key=object_key,
                ttl=expiry,
            )
        except ClientError as exc:
            logger.exception("DynamoDB error during idempotency check")
            raise TransientDynamoError from exc

        if not is_new:
            metrics.add_metric("DuplicatesSkipped", MetricUnit.Count, 1)
            return {}

        successful_records.append(s3_record)
        processed_message_ids.append(record.message_id)
        metrics.add_metric("NewObjectsProcessed", MetricUnit.Count, 1)
        return s3_record

    # -----------------------------------------------------
    # BatchProcessor orchestration (stage 1)
    # -----------------------------------------------------
    processor = BatchProcessor(
        event_type=EventType.SQS,
        raise_on_entire_batch_failure=False,  # ← don’t raise; always return failures list
    )

    with processor(records=event["Records"], handler=record_handler):
        processor.process()

    batch_failures: List[PartialItemFailures] = processor.response()["batchItemFailures"]

    logger.debug(
        "Stage‑1 complete",
        extra={"success_count": len(successful_records), "failure_count": len(batch_failures)},
    )

    # -----------------------------------------------------
    # Stage‑2 bundling
    # -----------------------------------------------------
    if successful_records:
        try:
            _process_successful_batch(successful_records, context, deps)
        except SQSBatchProcessingError:
            logger.error("Bundling failed — flagging processed items for retry", exc_info=True)
            for msg_id in processed_message_ids:
                batch_failures.append({"itemIdentifier": msg_id})

    # All duplicates – nothing sent or failed
    if not successful_records and not batch_failures:
        metrics.add_metric("DuplicateOnlyBatch", MetricUnit.Count, 1)
        logger.info("Batch contained only duplicates")

    logger.info("Batch finished", extra={"final_failure_count": len(batch_failures)})
    return {"batchItemFailures": batch_failures}

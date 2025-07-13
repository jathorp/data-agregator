# ─────────────────────────────────────────────────────────────
#  src/data_aggregator/app.py
# ─────────────────────────────────────────────────────────────
"""
SQS-triggered Lambda that:
  1. Filters duplicate S3 notifications via DynamoDB
  2. Bundles new objects into a gzip file
  3. Stages that bundle to both an archive and a distribution bucket
  4. Emits useful CloudWatch metrics
"""

from __future__ import annotations

import json
import os
import time
from functools import cached_property
from typing import Any, Dict, List, TypeAlias, cast
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

# ─────────────────────────────────────────────────────────────
#  Globals & constants
# ─────────────────────────────────────────────────────────────
S3EventRecord: TypeAlias = Dict[str, Any]

logger = Logger(service="data-aggregator")
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")

# Re-use boto3 clients across warm invocations (thread-safe)
_S3 = boto3.client("s3")
_DYNAMODB = boto3.client("dynamodb")


class SQSBatchProcessingError(Exception):
    """Raised when stage-2 bundle creation fails or time is exhausted."""


# ─────────────────────────────────────────────────────────────
#  Dependency container
# ─────────────────────────────────────────────────────────────
class Dependencies:
    """Lazy, per-invocation dependencies."""

    def __init__(self) -> None:
        self.idempotency_table = os.environ["IDEMPOTENCY_TABLE_NAME"]
        self.idempotency_ttl_seconds = int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7")) * 86_400
        self.archive_bucket = os.environ["ARCHIVE_BUCKET_NAME"]
        self.distribution_bucket = os.environ["DISTRIBUTION_BUCKET_NAME"]
        self.dynamodb_ttl_attribute = os.environ.get("DYNAMODB_TTL_ATTRIBUTE", "ttl")

    @cached_property
    def s3_client(self) -> S3Client:
        # Thin wrapper around the global _S3 client
        return S3Client(s3_client=_S3)

    @cached_property
    def dynamodb_client(self) -> DynamoDBClient:
        return DynamoDBClient(
            dynamo_client=_DYNAMODB,
            table_name=self.idempotency_table,
            ttl_attribute=self.dynamodb_ttl_attribute,
        )


# ─────────────────────────────────────────────────────────────
#  Record-level handler factory
# ─────────────────────────────────────────────────────────────
def make_record_handler(deps: Dependencies):
    """Returns a function that Powertools calls once per SQS record."""

    def record_handler(record: SQSRecord) -> S3EventRecord:  # pragma: no cover
        # 1. Parse and URL-decode the S3 key
        try:
            body: Dict[str, Any] = json.loads(record.body)
            s3_record: S3EventRecord = cast(S3EventRecord, body["Records"][0])
            object_key = unquote_plus(s3_record["s3"]["object"]["key"])
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Malformed SQS message – sending to DLQ", extra={"body": record.body})
            raise ValueError("Malformed SQS message") from exc

        # 2. Idempotency via DynamoDB
        expiry_ts = int(time.time()) + deps.idempotency_ttl_seconds
        try:
            is_new = deps.dynamodb_client.check_and_set_idempotency(object_key, expiry_ts)
        except ClientError as exc:
            logger.exception("DynamoDB idempotency call failed – retrying batch")
            raise SQSBatchProcessingError from exc

        if not is_new:
            metrics.add_metric("DuplicatesSkipped", MetricUnit.Count, 1)
            logger.debug("Duplicate key skipped", extra={"key": object_key})
            return {}

        logger.debug("New key accepted", extra={"key": object_key})
        return s3_record

    return record_handler


# ─────────────────────────────────────────────────────────────
#  Stage-2 bundle processing
# ─────────────────────────────────────────────────────────────
def _process_successful_batch(
    successful_records: List[Any],
    context: LambdaContext,
    deps: Dependencies,
) -> None:
    """Bundle objects and upload archive & distribution copies."""
    s3_records: List[S3EventRecord] = [cast(S3EventRecord, r.result) for r in successful_records]

    # Abort early if less than 5 s remain – avoids partial bundles
    if context.get_remaining_time_in_millis() < 5_000:
        raise SQSBatchProcessingError("Not enough time left to bundle")

    archive_key = f"bundle-{context.aws_request_id}.gz"

    process_and_stage_batch(
        records=s3_records,
        s3_client=deps.s3_client,
        archive_bucket=deps.archive_bucket,
        distribution_bucket=deps.distribution_bucket,
        archive_key=archive_key,
    )

    logger.info("Bundle created and staged", extra={"bundle_key": archive_key, "records": len(s3_records)})
    metrics.add_metric("BundlesCreated", MetricUnit.Count, 1)
    metrics.add_metric("RecordsInBundle", MetricUnit.Count, len(s3_records))


# ─────────────────────────────────────────────────────────────
#  Lambda entry point
# ─────────────────────────────────────────────────────────────
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    # 0. Validate event structure
    if not event.get("Records"):
        logger.warning("Empty or malformed event", extra={"event": event})
        return {"batchItemFailures": []}

    deps = Dependencies()
    processor = BatchProcessor(event_type=EventType.SQS)

    # 1. Record-level filtering & idempotency
    with processor(records=event["Records"], handler=make_record_handler(deps)):
        processor.process()

    # 2. Build partial-failure response
    batch_failures: List[PartialItemFailures] = processor.response()["batchItemFailures"]
    successful_records = [r for r in processor.success_messages if r.result]

    # 3. Stage bundle if anything new passed the filter
    if successful_records:
        try:
            _process_successful_batch(successful_records, context, deps)
        except SQSBatchProcessingError:
            logger.error("Stage-2 processing failed – returning successful items for retry")
            for rec in successful_records:
                batch_failures.append({"itemIdentifier": rec.message_id})  # type: ignore[dict-item]

    # 4. Operational clarity when *everything* was a duplicate
    if not batch_failures and not successful_records:
        logger.info("All records were duplicates – no work performed")

    return {"batchItemFailures": batch_failures}

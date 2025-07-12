# src/data_aggregator/app.py

import json
import os
import time
from functools import cached_property
from typing import Any, Dict, List, TypeAlias, cast

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailureResponse,
    PartialItemFailures,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import DynamoDBClient, S3Client
from .core import process_and_stage_batch

# Generic / shared definitions
S3EventRecord: TypeAlias = Dict[str, Any]
logger = Logger(service="data-aggregator")
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")
processor = BatchProcessor(event_type=EventType.SQS)

class SQSBatchProcessingError(Exception):
    """Raised when an entire SQS batch must be returned to the queue."""

class Dependencies:
    """Lazily-instantiated dependency container."""
    def __init__(self) -> None:
        # MODIFIED: Simplified environment variables
        self.idempotency_table: str = os.environ["IDEMPOTENCY_TABLE_NAME"]
        self.idempotency_ttl_seconds: int = (
            int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7")) * 86_400
        )
        self.archive_bucket: str = os.environ["ARCHIVE_BUCKET_NAME"]
        self.distribution_bucket: str = os.environ["DISTRIBUTION_BUCKET_NAME"]
        self.dynamodb_ttl_attribute: str = os.environ.get(
            "DYNAMODB_TTL_ATTRIBUTE", "ttl"
        )

    # MODIFIED: Removed http_session, secrets_provider, circuit_breaker_client, and nifi_client
    @cached_property
    def s3_client(self) -> S3Client:
        return S3Client(s3_client=boto3.client("s3"))

    @cached_property
    def dynamodb_client(self) -> DynamoDBClient:
        return DynamoDBClient(
            dynamo_client=boto3.client("dynamodb"),
            table_name=self.idempotency_table,
            ttl_attribute=self.dynamodb_ttl_attribute,
        )

def make_record_handler(dependencies: Dependencies):
    """Factory producing a per-invocation record handler."""
    def record_handler(record: SQSRecord) -> S3EventRecord:
        try:
            s3_event_body = json.loads(record.body)
            s3_record = cast(S3EventRecord, s3_event_body["Records"][0])
            object_key = s3_record["s3"]["object"]["key"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Malformed SQS message.", extra={"record": record.body})
            raise ValueError("Malformed SQS message body") from exc

        expiry_ts = int(time.time()) + dependencies.idempotency_ttl_seconds
        if dependencies.dynamodb_client.check_and_set_idempotency(object_key, expiry_ts):
            logger.info("New object key detected, adding to batch.", extra={"key": object_key})
            return s3_record

        logger.warning("Duplicate object key detected, skipping.", extra={"key": object_key})
        return {} # empty dict is ignored by BatchProcessor
    return record_handler

# MODIFIED: This function is now much simpler
def _process_successful_batch(
    successful_records: List[Any],
    context: LambdaContext,
    dependencies: Dependencies,
) -> None:
    """
    Stage-2 orchestration: create bundle, write to archive, write to distribution.
    """
    s3_records_to_process: List[S3EventRecord] = [
        cast(S3EventRecord, r.result) for r in successful_records
    ]

    try:
        # Use the AWS request ID to ensure a unique bundle name per invocation
        archive_key = f"bundle-{context.aws_request_id}.gz"
        process_and_stage_batch(
            records=s3_records_to_process,
            s3_client=dependencies.s3_client,
            archive_bucket=dependencies.archive_bucket,
            distribution_bucket=dependencies.distribution_bucket,
            archive_key=archive_key,
        )
        logger.info(
            "Successfully created and staged bundle.",
            extra={"bundle_key": archive_key, "record_count": len(s3_records_to_process)}
        )
    except Exception as exc:
        # Catch any exception during the core processing and fail the entire batch.
        logger.error("Failed to process and stage the batch.", exc_info=True)
        raise SQSBatchProcessingError("Batch processing failed") from exc

@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(
    event: Dict[str, Any], context: LambdaContext
) -> PartialItemFailureResponse:
    deps = Dependencies()
    with processor(records=event["Records"], handler=make_record_handler(deps)):
        pass

    batch_item_failures: List[PartialItemFailures] = processor.response()["batchItemFailures"]
    successful_records = [rec for rec in processor.success_messages if rec.result]

    if successful_records:
        try:
            _process_successful_batch(
                successful_records=successful_records,
                context=context,
                dependencies=deps,
            )
        except SQSBatchProcessingError:
            logger.error("Stage-2 processing failed. Returning all successful items to SQS for retry.")
            for record in successful_records:
                batch_item_failures.append(
                    cast(PartialItemFailures, {"itemIdentifier": record.message_id})
                )

    return {"batchItemFailures": batch_item_failures}
# src/data_aggregator/app.py

"""
Main AWS Lambda handler for the Data Aggregator service.

This module is the entry point for an SQS-triggered Lambda function. Its primary
responsibilities are:
- Process batches of SQS messages, which contain S3 event notifications.
- Ensure messages are processed exactly once using an idempotency store.
- Group successfully processed S3 object references into a batch.
- Trigger a core bundling process to create a compressed archive (.tar.gz).
- Handle partial batch failures gracefully, returning failed message IDs to SQS
  for automatic retry.
"""

from __future__ import annotations

import json
import os
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from typing import Any, Dict, List, cast

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailureResponse,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSEvent
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    IdempotencyConfig,
    idempotent_function,
)
from aws_lambda_powertools.utilities.idempotency.exceptions import (
    IdempotencyItemAlreadyExistsError,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import S3Client
from .core import process_and_stage_batch
from .exceptions import (
    BatchTooLargeError,
    BundlingTimeoutError,
    SQSBatchProcessingError,
)
from .schemas import S3EventRecord


###############################################################################
# Old code
###############################################################################

# class Dependencies:
#     """
#     Lazily-instantiated façade around all external services
#     (boto3 clients, requests.Session, SecretsManager, …).
#
#     A new instance is created _inside_ every Lambda invocation so tests
#     can inject stubs and no state leaks between warm containers.
#     """
#
#     """Lazily-instantiated dependency container."""
#     def __init__(self) -> None:
#         self.idempotency_table: str = os.environ["IDEMPOTENCY_TABLE_NAME"]
#         self.idempotency_ttl_seconds: int = (
#             int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7")) * 86_400
#         )
#         self.archive_bucket: str = os.environ["ARCHIVE_BUCKET_NAME"]
#         self.nifi_endpoint_url: str = os.environ["NIFI_ENDPOINT_URL"]
#         self.nifi_connect_timeout: int = int(
#             os.environ.get("NIFI_CONNECT_TIMEOUT_SECONDS", "5")
#         )
#         self.nifi_secret_arn: str = os.environ["NIFI_SECRET_ARN"]
#         self.circuit_breaker_table: str = os.environ["CIRCUIT_BREAKER_TABLE_NAME"]
#         self.cb_failure_threshold: int = int(
#             os.environ.get("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
#         )
#         self.cb_open_seconds: int = int(
#             os.environ.get("CIRCUIT_BREAKER_OPEN_SECONDS", "300")
#         )
#         self.distribution_bucket: str = os.environ["DISTRIBUTION_BUCKET_NAME"]
#         self.dynamodb_ttl_attribute: str = os.environ.get(
#             "DYNAMODB_TTL_ATTRIBUTE", "ttl"
#         )
#
#     @cached_property
#     def metrics(self) -> Metrics:
#         return metrics
#
#     # MODIFIED: Removed http_session, secrets_provider, circuit_breaker_client, and nifi_client
#     @cached_property
#     def s3_client(self) -> S3Client:
#         return S3Client(s3_client=boto3.client("s3"))


###############################################################################
# Configuration
###############################################################################


@dataclass(frozen=True, slots=True)
class AppConfig:
    idempotency_table: str = os.getenv(
        "IDEMPOTENCY_TABLE_NAME", "dummy-idempotency-table"
    )
    distribution_bucket: str = os.getenv(
        "DISTRIBUTION_BUCKET_NAME", "dummy-distribution-bucket"
    )
    environment: str = os.getenv("ENV", "dev")
    idempotency_ttl_days: int = int(os.getenv("IDEMPOTENCY_TTL_DAYS", "7"))
    bundle_kms_key_id: str | None = os.getenv("BUNDLE_KMS_KEY_ID")
    max_bundle_input_mb: int = int(os.getenv("MAX_BUNDLE_INPUT_MB", "100"))
    bundling_safety_ms: int = int(os.getenv("BUNDLING_SAFETY_MS", "8000"))

    @property
    def idempotency_ttl_seconds(self) -> int:
        return self.idempotency_ttl_days * 86_400

    @property
    def max_bundle_input_bytes(self) -> int:
        return self.max_bundle_input_mb * 1_048_576


CONFIG = AppConfig()

###############################################################################
# Observability primitives
###############################################################################

logger = Logger(service="data-aggregator")
logger.append_keys(environment=CONFIG.environment)
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")
metrics.set_default_dimensions(environment=CONFIG.environment)


###############################################################################
# AWS clients & Idempotency Store
###############################################################################

_REGION = (
    os.getenv("AWS_REGION")  # set automatically in Lambda
    or os.getenv("AWS_DEFAULT_REGION")  # recognised by the AWS CLI / SDKs
    or "us-east-1"  # safe fallback for local tests
)

_S3 = boto3.client("s3", region_name=_REGION)
_DYNAMODB = boto3.client("dynamodb", region_name=_REGION)

# QA Note (Dynamo Hot Keys): With a bucket/key PK, bursts of updates to the
# same S3 object could create a hot partition in DynamoDB. For high-throughput
# systems, consider enabling on-demand capacity or using a composite key
# (e.g., with a hashed prefix) to improve write distribution.
persistence_layer = DynamoDBPersistenceLayer(
    table_name=CONFIG.idempotency_table, boto3_client=_DYNAMODB
)

# QA Note (Idempotency Key): The JMESPath is evaluated against the `s3_record`
# object passed to `_guard_uniqueness`. The structure of `s3_record` is
# `{"s3": {"bucket": {"name": ...}, "object": {"key": ...}}}`.
# Therefore, this path correctly extracts the bucket and key.
idempotency_config = IdempotencyConfig(
    event_key_jmespath="[s3.bucket.name, s3.object.key]",
    expires_after_seconds=CONFIG.idempotency_ttl_seconds,
)


@idempotent_function(
    data_keyword_argument="s3_record",
    config=idempotency_config,
    persistence_store=persistence_layer,
)
def _guard_uniqueness(s3_record: S3EventRecord) -> None:
    """
    Wrap a function call with an idempotency check.

    This function is a placeholder for the idempotency decorator, which ensures
    that an S3 object is processed only once. It raises
    IdempotencyItemAlreadyExistsError if the key is already in the store.

    Args:
        s3_record: The parsed S3 event record to check for uniqueness.
    """
    pass


###############################################################################
# Dependency container
###############################################################################


class Dependencies:
    """
    A container for managing and lazy-loading dependencies like AWS clients.
    This pattern makes mocking for tests straightforward.
    """

    @cached_property
    def s3_client(self) -> S3Client:  # pragma: no cover
        """Provides a singleton instance of the S3Client wrapper."""
        return S3Client(s3_client=_S3, kms_key_id=CONFIG.bundle_kms_key_id)


###############################################################################
# Business Logic Helpers
###############################################################################


@tracer.capture_method(capture_response=False)
def _process_successful_batch(
    successful_records: List[S3EventRecord],
    context: LambdaContext,
    deps: Dependencies,
) -> None:
    """
    Orchestrate the bundling and uploading of a batch of S3 objects.

    Args:
        successful_records: A list of validated S3 event records to be bundled.
        context: The AWS Lambda context object.
        deps: The dependency container with initialized clients.

    Raises:
        BatchTooLargeError: If the combined size of objects exceeds the limit.
        BundlingTimeoutError: If there is not enough time remaining to proceed.
        SQSBatchProcessingError: For other bundling failures that require a retry.
    """
    logger.debug("Stage-2 processing", extra={"record_count": len(successful_records)})

    # QA Fix: Use .get("size", 0) as the size attribute is optional in S3 events.
    total_input = sum(r["s3"]["object"].get("size", 0) for r in successful_records)
    if total_input > CONFIG.max_bundle_input_bytes:
        raise BatchTooLargeError(f"Batch is {total_input} bytes > limit")

    if context.get_remaining_time_in_millis() < CONFIG.bundling_safety_ms:
        raise BundlingTimeoutError("Not enough time left to bundle")

    # Use a date-based prefix for S3 partitioning and a random suffix for uniqueness.
    now = datetime.now(timezone.utc)
    key_prefix = now.strftime("%Y/%m/%d/%H")
    bundle_key = (
        f"{key_prefix}/bundle-{context.aws_request_id}-{secrets.token_hex(4)}.gz"
    )

    with tracer.provider.in_subsegment("process_and_stage_bundle"):
        process_and_stage_batch(
            records=successful_records,
            s3_client=deps.s3_client,
            distribution_bucket=CONFIG.distribution_bucket,
            bundle_key=bundle_key,
            context=context,
        )

    metrics.add_metric("BundlesCreated", MetricUnit.Count, 1)
    metrics.add_metric("RecordsInBundle", MetricUnit.Count, len(successful_records))
    logger.info("Bundle staged", extra={"key": bundle_key})


def _record_handler(
    record: dict,
    successes: list[S3EventRecord],
    msg_ids: list[str],
    metrics_counter: Counter,
) -> None:
    """
    Validate one SQS message, guard idempotency, and collect successes.

    This handler is designed to be called by the BatchProcessor.

    Args:
        record: The raw SQS record dictionary to process.
        successes: A list to append successful S3EventRecord data to.
        msg_ids: A list to append the message ID of successful records to.
        metrics_counter: A counter to aggregate metrics for batch flushing.

    Raises:
        ValueError: If the SQS message body is malformed.
    """
    try:
        body: Dict[str, Any] = json.loads(record["body"])
        s3_record: S3EventRecord = cast(S3EventRecord, body["Records"][0])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        logger.warning("Malformed SQS message", extra={"body": record.get("body")})
        raise ValueError("Malformed SQS message") from e

    try:
        _guard_uniqueness(s3_record=s3_record)
        successes.append(s3_record)
        msg_ids.append(record["messageId"])
        metrics_counter["NewObjectsProcessed"] += 1
    except IdempotencyItemAlreadyExistsError:
        metrics_counter["DuplicatesSkipped"] += 1
        logger.debug("Duplicate skipped", extra={"record": s3_record})


###############################################################################
# Lambda Entry-Point
###############################################################################

processor = BatchProcessor(
    event_type=EventType.SQS,
    raise_on_entire_batch_failure=False,
)


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: SQSEvent, context: LambdaContext) -> PartialItemFailureResponse:
    """
    The main Lambda handler for processing SQS message batches.

    It uses the Powertools BatchProcessor to handle per-item failures.
    Successful items are collected and passed to a bundling function. If the
    bundling process fails, the entire batch is marked for retry by SQS.

    Args:
        event: The incoming SQSEvent object containing the records.
        context: The AWS Lambda context object.

    Returns:
        A dictionary containing a list of failed item identifiers, which SQS
        will then retry.
    """
    if not event.records:
        logger.warning("No records received in the event.")
        return {"batchItemFailures": []}

    idempotency_config.register_lambda_context(context)
    deps = Dependencies()

    successful_records: list[S3EventRecord] = []
    processed_msg_ids: list[str] = []
    # Perf Fix: Aggregate per-record metrics locally to reduce CloudWatch API calls.
    stage1_metrics = Counter()

    # --- Stage-1 (per-message validation) ---
    def record_handler(rec: dict):
        """A closure that calls the main record handler with the metrics counter."""
        _record_handler(rec, successful_records, processed_msg_ids, stage1_metrics)

    # Perf Fix: Pass the list comprehension directly to the processor to avoid
    # creating an intermediate list in memory.
    with processor(
        records=[rec.raw_event for rec in event.records], handler=record_handler
    ):
        processor.process()

    # Flush batched metrics from Stage 1
    for metric_name, value in stage1_metrics.items():
        if value > 0:
            metrics.add_metric(name=metric_name, unit=MetricUnit.Count, value=value)

    batch_failures = processor.response()["batchItemFailures"]

    logger.debug(
        "Stage-1 complete",
        extra={
            "success_count": len(successful_records),
            "failure_count": len(batch_failures),
        },
    )

    # --- Stage-2 (bundle & upload) ---
    if successful_records:
        try:
            _process_successful_batch(successful_records, context, deps)
        except SQSBatchProcessingError:
            logger.error(
                "Bundling failed - flagging all successfully processed items for retry",
                exc_info=True,
            )
            # QA Fix: De-duplicate failure reporting.
            failed_ids_in_stage1 = {item["itemIdentifier"] for item in batch_failures}
            for msg_id in processed_msg_ids:
                if msg_id not in failed_ids_in_stage1:
                    batch_failures.append({"itemIdentifier": msg_id})

    if not successful_records and not batch_failures:
        metrics.add_metric("DuplicateOnlyBatch", MetricUnit.Count, 1)
        logger.info("Batch contained only duplicates, no action needed.")

    logger.info("Batch finished", extra={"final_failure_count": len(batch_failures)})
    return {"batchItemFailures": batch_failures}

# data_aggregator/app.py


import json
import os
import time
from functools import cached_property
from typing import Any, Dict, List, TypeAlias, cast

import boto3
import requests
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailureResponse,
    PartialItemFailures,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import CircuitBreakerClient, DynamoDBClient, NiFiClient, S3Client
from .core import process_and_deliver_batch

# ----------------------------
# Generic / shared definitions
# ----------------------------

S3EventRecord: TypeAlias = Dict[str, Any]

logger = Logger(service="data-aggregator")
tracer = Tracer(service="data-aggregator")
metrics = Metrics(namespace="DataAggregator", service="data-aggregator")
processor = BatchProcessor(event_type=EventType.SQS)


class SQSBatchProcessingError(Exception):
    """Raised when an entire SQS batch must be returned to the queue."""


# ----------------------------
# Dependency container
# ----------------------------


class Dependencies:
    """
    Lazily-instantiated façade around all external services
    (boto3 clients, requests.Session, SecretsManager, …).

    A new instance is created _inside_ every Lambda invocation so tests
    can inject stubs and no state leaks between warm containers.
    """

    def __init__(self) -> None:
        self.idempotency_table: str = os.environ["IDEMPOTENCY_TABLE_NAME"]
        self.idempotency_ttl_seconds: int = (
            int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7")) * 86_400
        )
        self.archive_bucket: str = os.environ["ARCHIVE_BUCKET_NAME"]
        self.nifi_endpoint_url: str = os.environ["NIFI_ENDPOINT_URL"]
        self.nifi_connect_timeout: int = int(
            os.environ.get("NIFI_CONNECT_TIMEOUT_SECONDS", "5")
        )
        self.nifi_secret_arn: str = os.environ["NIFI_SECRET_ARN"]
        self.circuit_breaker_table: str = os.environ["CIRCUIT_BREAKER_TABLE_NAME"]
        self.cb_failure_threshold: int = int(
            os.environ.get("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
        )
        self.cb_open_seconds: int = int(
            os.environ.get("CIRCUIT_BREAKER_OPEN_SECONDS", "300")
        )
        self.dynamodb_ttl_attribute: str = os.environ.get(
            "DYNAMODB_TTL_ATTRIBUTE", "ttl"
        )

    @cached_property
    def metrics(self) -> Metrics:
        return metrics

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

    @cached_property
    def circuit_breaker_client(self) -> CircuitBreakerClient:
        return CircuitBreakerClient(
            dynamo_client=boto3.client("dynamodb"),
            table_name=self.circuit_breaker_table,
            metrics=self.metrics,
            failure_threshold=self.cb_failure_threshold,
            open_duration_seconds=self.cb_open_seconds,
        )

    @cached_property
    def http_session(self) -> requests.Session:
        return requests.Session()

    @cached_property
    def secrets_provider(self) -> SecretsProvider:
        return SecretsProvider()

    @cached_property
    def nifi_client(self) -> NiFiClient:
        nifi_creds = self.secrets_provider.get(self.nifi_secret_arn, transform="json")
        return NiFiClient(
            session=self.http_session,
            endpoint_url=self.nifi_endpoint_url,
            auth=(nifi_creds["username"], nifi_creds["password"]),
            connect_timeout=self.nifi_connect_timeout,
        )


# ----------------------------
# Helpers – pure business code
# ----------------------------


def deliver_records(
    records: List[S3EventRecord],
    dependencies: Dependencies,
    archive_key: str,
    read_timeout: int,
) -> None:
    """
    Thin wrapper around core.process_and_deliver_batch so that the heavy‑lifting
    logic can be unit‑tested without touching BatchProcessor or Lambda context.
    """
    process_and_deliver_batch(
        records=records,
        s3_client=dependencies.s3_client,
        nifi_client=dependencies.nifi_client,
        archive_bucket=dependencies.archive_bucket,
        archive_key=archive_key,
        read_timeout=read_timeout,
    )


def make_record_handler(dependencies: Dependencies):
    """
    Factory producing a per‑invocation record handler with injected dependencies.
    """

    def record_handler(record: SQSRecord) -> S3EventRecord:
        try:
            s3_event_body = json.loads(record.body)
            s3_record = cast(S3EventRecord, s3_event_body["Records"][0])
            object_key = s3_record["s3"]["object"]["key"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Malformed SQS message.", extra={"record": record.body})
            raise ValueError("Malformed SQS message body") from exc

        expiry_ts = int(time.time()) + dependencies.idempotency_ttl_seconds
        if dependencies.dynamodb_client.check_and_set_idempotency(
            object_key, expiry_ts
        ):
            logger.info(
                "New object key detected, adding to batch.", extra={"key": object_key}
            )
            return s3_record

        logger.warning(
            "Duplicate object key detected, skipping.", extra={"key": object_key}
        )
        return {}  # empty dict is ignored by BatchProcessor

    return record_handler


def _process_successful_batch(
    successful_records: List[Any],  # powertools internal wrapper objects
    context: LambdaContext,
    dependencies: Dependencies,
) -> List[PartialItemFailures]:
    """
    Stage‑2 orchestration: bundle upload, NiFi delivery,
    circuit‑breaker bookkeeping, half‑open logic.
    """
    breaker_state = dependencies.circuit_breaker_client.get_state()
    if breaker_state == "OPEN":
        logger.error("Circuit breaker is OPEN. Failing entire batch.")
        raise SQSBatchProcessingError("Circuit Breaker is open")

    # unwrap BatchProcessor's RecordWrapper → original S3 event record
    s3_records_to_process: List[S3EventRecord] = [
        cast(S3EventRecord, r.result) for r in successful_records
    ]
    records_for_run = (
        s3_records_to_process[:1]
        if breaker_state == "HALF_OPEN"
        else s3_records_to_process
    )

    remaining_time_ms = context.get_remaining_time_in_millis()
    read_timeout = max((remaining_time_ms / 1000) - 8, 5)

    try:
        archive_key = f"bundle-{context.aws_request_id}.gz"
        deliver_records(
            records_for_run,
            dependencies=dependencies,
            archive_key=archive_key,
            read_timeout=int(read_timeout),
        )
        dependencies.circuit_breaker_client.record_success()

        # Half‑open probe succeeded – return the _other_ messages so SQS re‑queues them
        if breaker_state == "HALF_OPEN" and len(s3_records_to_process) > 1:
            logger.info(
                "HALF_OPEN probe succeeded. Returning remaining messages to SQS."
            )
            return [
                cast(PartialItemFailures, {"itemIdentifier": record.message_id})
                for record in successful_records[1:]
            ]

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        logger.error("Request to NiFi timed out or connection failed.", exc_info=True)
        dependencies.circuit_breaker_client.record_failure()
        raise SQSBatchProcessingError("Downstream connection error") from exc

    return []


# ----------------------------
# Lambda entry‑point
# ----------------------------


# This decorator will automatically capture and publish all metrics
# added during the handler's execution in the correct EMF format.
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(
    event: Dict[str, Any], context: LambdaContext
) -> PartialItemFailureResponse:
    deps = Dependencies()
    with processor(
        records=event["Records"],
        handler=make_record_handler(deps),
    ):
        pass

    # start with any per‑record failures already detected by BatchProcessor
    batch_item_failures: List[PartialItemFailures] = processor.response()[
        "batchItemFailures"
    ]

    successful_records = [
        rec
        for rec in processor.success_messages
        if rec.result  # those passed idempotency
    ]

    if successful_records:
        try:
            half_open_failures = _process_successful_batch(
                successful_records=successful_records,
                context=context,
                dependencies=deps,
            )
            batch_item_failures.extend(half_open_failures)

        except SQSBatchProcessingError:
            logger.error(
                "Stage‑2 processing failed. Returning earlier successful items to SQS."
            )
            for record in successful_records:
                batch_item_failures.append(
                    cast(PartialItemFailures, {"itemIdentifier": record.message_id})
                )

    return {"batchItemFailures": batch_item_failures}

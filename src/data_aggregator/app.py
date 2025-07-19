# src/data_aggregator/app.py

"""
The Lambda Adapter & Orchestrator for the Data Aggregator service.

This module is the main entry point for the AWS Lambda function. It is
responsible for:
1.  Initializing and configuring AWS Lambda Powertools (Logger, Tracer, Metrics,
    and Idempotency).
2.  Parsing and validating incoming SQS messages containing S3 event notifications.
3.  Orchestrating the idempotency check for each incoming S3 object to ensure
    exactly-once processing.
4.  Aggregating valid, non-duplicate records into a single batch.
5.  Invoking the core business logic (`process_and_stage_batch`) to create and
    upload the final Gzip bundle.
6.  Implementing robust partial batch failure handling.
"""

import json
from datetime import datetime, timezone
from typing import Any, List, Set, cast

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailures,
    PartialItemFailureResponse,
)
from aws_lambda_powertools.utilities.idempotency import (
    IdempotencyConfig,
    idempotent_function,
)
from aws_lambda_powertools.utilities.idempotency.exceptions import (
    IdempotencyItemAlreadyExistsError,
)
from aws_lambda_powertools.utilities.idempotency.persistence.dynamodb import (
    DynamoDBPersistenceLayer,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import S3Client
from .config import get_config
from .core import process_and_stage_batch
from .schemas import S3EventRecord

# --- Global & Reusable Components ---
CONFIG = get_config()

logger = Logger(service=CONFIG.service_name, level=CONFIG.log_level)
# REMOVED: Redundant key. Set shared dimensions on Metrics only.
# logger.append_keys(environment=CONFIG.environment)
tracer = Tracer(service=CONFIG.service_name)
metrics = Metrics(namespace="DataAggregator", service=CONFIG.service_name)
metrics.set_default_dimensions(environment=CONFIG.environment)

s3_boto_client = boto3.client("s3")
s3_client = S3Client(s3_client=s3_boto_client)

idempotency_persistence_layer = DynamoDBPersistenceLayer(
    table_name=CONFIG.idempotency_table,
    key_attr="object_key",
)

idempotency_config = IdempotencyConfig(
    event_key_jmespath="idempotency_key",
    payload_validation_jmespath="s3_object.size",
    expires_after_seconds=CONFIG.idempotency_ttl_seconds,
    use_local_cache=True,
    raise_on_no_idempotency_key=True,
)

# Set the primary key name for the persistence layer that the idempotency utility will use.
# THIS IS CRITICAL. The idempotency decorator will now look for 'object_key' in its config.
idempotency_config.jmespath_options = {"idempotency_key_jmespath": "idempotency_key"}
idempotency_persistence_layer.configure(config=idempotency_config)

@idempotent_function(
    data_keyword_argument="data",
    config=idempotency_config,
    persistence_store=idempotency_persistence_layer,
)
def _process_record_idempotently(*, data: dict[str, Any]) -> bool:
    """Wraps the idempotency check. If it runs, the item is not a duplicate."""
    logger.debug("Idempotency check passed for new item.", extra=data)
    return True


def build_partial_failure_response(
    failed_message_ids: set[str],
) -> PartialItemFailureResponse:
    """
    Given a set of SQS message IDs, return the structure that the
    Lambda partial batch response API expects.
    """
    failures = [
        cast(PartialItemFailures, {"itemIdentifier": mid}) for mid in failed_message_ids
    ]
    response = cast(PartialItemFailureResponse, {"batchItemFailures": failures})
    return response


def _get_message_ids_for_s3_records(
    s3_records: List[S3EventRecord],
    record_to_message_id_map: dict[str, set[str]],
) -> Set[str]:
    """Finds all unique SQS message IDs for a given list of S3 records."""
    message_ids: Set[str] = set()
    for record in s3_records:
        s3_key = record["s3"]["object"]["key"]
        s3_version = record["s3"]["object"].get("versionId")
        unique_record_key = f"{s3_key}#{s3_version}" if s3_version else s3_key
        ids_for_record = record_to_message_id_map.get(unique_record_key, set())
        message_ids.update(ids_for_record)
    return message_ids


def _process_valid_records(
    records_to_process: List[S3EventRecord],
    record_to_message_id_map: dict[str, set[str]],
    context: LambdaContext,
) -> Set[str]:
    """Takes valid S3 records, bundles them, and returns SQS message IDs for any unprocessed records."""
    now = datetime.now(timezone.utc)
    bundle_key = f"{now.strftime('%Y/%m/%d/%H')}/bundle-{context.aws_request_id}.tar.gz"

    _, _, remaining_records = process_and_stage_batch(
        records=records_to_process,
        s3_client=s3_client,
        distribution_bucket=CONFIG.distribution_bucket,
        bundle_key=bundle_key,
        context=context,
    )

    processed_count = len(records_to_process) - len(remaining_records)
    metrics.add_metric(
        name="ProcessedRecordsInBundle", unit=MetricUnit.Count, value=processed_count
    )

    if not remaining_records:
        return set()

    metrics.add_metric(
        name="RemainingRecordsForRetry",
        unit=MetricUnit.Count,
        value=len(remaining_records),
    )
    logger.warning(
        "Some records were not processed due to constraints and will be retried.",
        extra={
            "remaining_count": len(remaining_records),
            "example_keys": [r["s3"]["object"]["key"] for r in remaining_records[:3]],
        },
    )

    return _get_message_ids_for_s3_records(remaining_records, record_to_message_id_map)


@logger.inject_lambda_context(log_event=True, correlation_id_path="aws_request_id")
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    """Main Lambda handler to process a batch of S3 events from SQS."""
    # FIX 2: Register the Lambda context for idempotency timeout calculations
    idempotency_config.register_lambda_context(context)

    sqs_records: list[dict] = event.get("Records", [])
    if not sqs_records:
        logger.warning("Event did not contain any SQS records. Exiting gracefully.")
        return {"batchItemFailures": []}

    # --- Setup tracking variables ---
    records_to_process: List[S3EventRecord] = []
    failed_message_ids: Set[str] = set()
    record_to_message_id_map: dict[str, set[str]] = {}

    # --- 1. First Pass: Parse, build lookup map, and run idempotency checks ---
    for sqs_record in sqs_records:
        message_id = sqs_record["messageId"]
        try:
            s3_event = json.loads(sqs_record["body"])
            s3_records = s3_event.get("Records")
            if not s3_records:
                raise KeyError("'Records' list is missing or empty.")
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "Failed to parse SQS message body.",
                extra={"messageId": message_id, "error": str(e)},
            )
            failed_message_ids.add(message_id)
            continue

        for s3_record in s3_records:
            idempotency_key = ""
            try:
                s3_object = s3_record["s3"]["object"]
                s3_key = s3_object["key"]
                s3_version = s3_object.get("versionId")
                unique_record_key = f"{s3_key}#{s3_version}" if s3_version else s3_key

                record_to_message_id_map.setdefault(unique_record_key, set()).add(
                    message_id
                )

                idempotency_key = (
                    f"{s3_record['s3']['bucket']['name']}/{unique_record_key}"
                )
                payload = {"idempotency_key": idempotency_key, "s3_object": s3_object}
                _process_record_idempotently(data=payload)

                records_to_process.append(s3_record)

            except IdempotencyItemAlreadyExistsError:
                metrics.add_metric(
                    name="FailedIdempotencyChecks", unit=MetricUnit.Count, value=1
                )
                logger.info(
                    "Skipping duplicate S3 object.",
                    extra={"idempotency_key": idempotency_key},
                )
            except Exception:
                logger.exception(
                    "Failed to process an S3 record.", extra={"messageId": message_id}
                )
                failed_message_ids.add(message_id)

    # --- 2. If no new valid records, exit now ---
    if not records_to_process:
        logger.info("No new records to process after filtering duplicates and errors.")
        return build_partial_failure_response(failed_message_ids)

    # --- 3. Process the valid batch ---
    try:
        unprocessed_ids = _process_valid_records(
            records_to_process, record_to_message_id_map, context
        )
        failed_message_ids.update(unprocessed_ids)
    except Exception:
        logger.exception("A non-recoverable error occurred during bundling.")
        all_contributing_message_ids = _get_message_ids_for_s3_records(
            records_to_process, record_to_message_id_map
        )
        return build_partial_failure_response(all_contributing_message_ids)

    # --- 4. Return the final result ---
    if failed_message_ids:
        return build_partial_failure_response(failed_message_ids)

    return {"batchItemFailures": []}
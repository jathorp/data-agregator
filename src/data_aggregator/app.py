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
from typing import Any, cast
from urllib.parse import quote

import boto3
import pydantic
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
from .exceptions import (
    BundleCreationError,
    DataAggregatorError,
    DiskSpaceError,
    MemoryLimitError,
    S3AccessDeniedError,
    S3ThrottlingError,
    S3TimeoutError,
    get_error_context,
    is_retryable_error,
)
from .schemas import S3EventNotificationRecord

# --- Global & Reusable Components ---
CONFIG = get_config()

logger = Logger(service=CONFIG.service_name, level=CONFIG.log_level)
tracer = Tracer(service=CONFIG.service_name)
metrics = Metrics(
    namespace="DataAggregator",
    service=CONFIG.service_name,
)

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
idempotency_persistence_layer.configure(config=idempotency_config)


# ───────────────────────────────────────────────────────────────
# Helper: collision‑proof idempotency key
# ───────────────────────────────────────────────────────────────
def _make_idempotency_key(key: str, version: str | None, sequencer: str) -> str:
    """
    Deterministic, collision-proof key based on object key, version, and sequencer.
    This intentionally excludes the bucket to de-duplicate the same file
    if it appears in different buckets.

    For versioned buckets, versionId provides uniqueness.
    For unversioned buckets, the sequencer guarantees uniqueness for each modification.
    """
    # Use versionId if it exists, otherwise fall back to the sequencer.
    unique_part = version or sequencer
    raw = json.dumps({"k": key, "u": unique_part}, separators=(",", ":"))
    return quote(raw, safe="")


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
    s3_records: list[S3EventNotificationRecord],
    record_to_message_id_map: dict[str, set[str]],
) -> set[str]:
    """Finds all unique SQS message IDs for a given list of S3 records."""
    message_ids: set[str] = set()
    for record in s3_records:
        # Reconstruct the key in exactly the same way to ensure a match.
        original_s3_key = record.s3.object.original_key
        s3_version = record.s3.object.version_id
        s3_sequencer = record.s3.object.sequencer

        unique_record_key = _make_idempotency_key(
            original_s3_key, s3_version, s3_sequencer
        )

        ids_for_record = record_to_message_id_map.get(unique_record_key, set())
        message_ids.update(ids_for_record)

    return message_ids


def _process_valid_records(
    records_to_process: list[S3EventNotificationRecord],
    record_to_message_id_map: dict[str, set[str]],
    context: LambdaContext,
) -> set[str]:
    """Takes valid S3 records, bundles them, and returns SQS message IDs for any unprocessed records."""
    now = datetime.now(timezone.utc)
    bundle_key = f"{now.strftime('%Y/%m/%d/%H')}/bundle-{context.aws_request_id}.tar.gz"

    # Calculate total size for logging
    total_size_bytes = sum(record.s3.object.size for record in records_to_process)
    
    logger.info(
        "Starting bundle creation",
        extra={
            "records_count": len(records_to_process),
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "bundle_key": bundle_key,
        },
    )

    try:
        _, _, remaining_records = process_and_stage_batch(
            records=records_to_process,
            s3_client=s3_client,
            distribution_bucket=CONFIG.distribution_bucket,
            bundle_key=bundle_key,
            context=context,
            config=CONFIG,
        )

        processed_count = len(records_to_process) - len(remaining_records)
        processed_size_bytes = sum(
            record.s3.object.size 
            for record in records_to_process 
            if record not in remaining_records
        )
        
        metrics.add_metric(
            name="ProcessedRecordsInBundle",
            unit=MetricUnit.Count,
            value=processed_count,
        )

        if not remaining_records:
            # Extract bundled file names for debugging
            bundled_files = [
                f"{record.s3.bucket.name}/{record.s3.object.original_key}"
                for record in records_to_process
                if record not in remaining_records
            ]
            
            logger.info(
                "Bundle creation completed successfully",
                extra={
                    "processed_records": processed_count,
                    "processed_size_mb": round(processed_size_bytes / (1024 * 1024), 2),
                    "bundle_key": bundle_key,
                    "bundled_files": bundled_files,
                },
            )
            return set()

        metrics.add_metric(
            name="RemainingRecordsForRetry",
            unit=MetricUnit.Count,
            value=len(remaining_records),
        )
        logger.warning(
            "Bundle creation partially completed - some records will be retried",
            extra={
                "processed_records": processed_count,
                "remaining_count": len(remaining_records),
                "processed_size_mb": round(processed_size_bytes / (1024 * 1024), 2),
                "bundle_key": bundle_key,
            },
        )
        return _get_message_ids_for_s3_records(
            remaining_records, record_to_message_id_map
        )

    except (MemoryLimitError, DiskSpaceError) as e:
        # Critical resource errors - fail all records for retry
        metrics.add_metric(
            name="CriticalResourceErrors", unit=MetricUnit.Count, value=1
        )
        logger.error(
            f"Critical resource error during batch processing: {e}",
            extra=get_error_context(e),
        )
        # Return all message IDs for retry
        return _get_message_ids_for_s3_records(
            records_to_process, record_to_message_id_map
        )

    except BundleCreationError as e:
        # Bundle creation errors - determine if retryable
        if is_retryable_error(e):
            metrics.add_metric(
                name="RetryableBundleErrors", unit=MetricUnit.Count, value=1
            )
            logger.warning(
                f"Retryable bundle creation error: {e}", extra=get_error_context(e)
            )
            # Return all message IDs for retry
            return _get_message_ids_for_s3_records(
                records_to_process, record_to_message_id_map
            )
        else:
            metrics.add_metric(
                name="NonRetryableBundleErrors", unit=MetricUnit.Count, value=1
            )
            logger.error(
                f"Non-retryable bundle creation error: {e}", extra=get_error_context(e)
            )
            # Don't retry non-retryable errors
            return set()

    except (S3ThrottlingError, S3TimeoutError) as e:
        # Retryable S3 errors
        metrics.add_metric(name="RetryableS3Errors", unit=MetricUnit.Count, value=1)
        logger.warning(
            f"Retryable S3 error during batch processing: {e}",
            extra=get_error_context(e),
        )
        # Return all message IDs for retry
        return _get_message_ids_for_s3_records(
            records_to_process, record_to_message_id_map
        )

    except S3AccessDeniedError as e:
        # Non-retryable errors
        metrics.add_metric(name="NonRetryableErrors", unit=MetricUnit.Count, value=1)
        logger.error(
            f"Non-retryable error during batch processing: {e}",
            extra=get_error_context(e),
        )
        # Don't retry non-retryable errors
        return set()

    except DataAggregatorError as e:
        error_details = get_error_context(e)
        retryable = error_details["retryable"]

        metrics.add_metric(
            name="RetryableAppErrors" if retryable else "NonRetryableAppErrors",
            unit=MetricUnit.Count,
            value=1,
        )

        # Log error without sensitive data - get_error_context already sanitizes
        log_level = logger.warning if retryable else logger.error
        log_level(
            f"Application error during batch processing: {e}", 
            extra={
                "error_type": error_details.get("error_type"),
                "retryable": retryable,
                "records_count": len(records_to_process),
            }
        )

        if retryable:
            return _get_message_ids_for_s3_records(
                records_to_process, record_to_message_id_map
            )
        else:
            return set()


@logger.inject_lambda_context()
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    """Main Lambda handler for SQS events and direct test invocations."""
    metrics.add_dimension("environment", CONFIG.environment)
    idempotency_config.register_lambda_context(context)
    is_test_env = CONFIG.environment.lower() in {"dev", "test"}

    # --- START OF TEST ROUTING LOGIC ---

    # Path1: Direct invocation for the bundling (e.g., disk limit) test.
    if event.get("e2e_test_direct_invoke"):
        if not is_test_env:
            logger.error("Test-only bundling invoke received in production.")
            raise ValueError("e2e_test_direct_invoke not allowed in this environment")
        logger.info("Direct invocation test for bundling detected.")
        raw_records = event.get("records", [])

        # Parse the raw test records into Pydantic models ---
        try:
            # Use a list comprehension to parse each raw dictionary
            records_to_process = [
                S3EventNotificationRecord.model_validate(r) for r in raw_records
            ]
        except pydantic.ValidationError as e:
            logger.error(
                "Invalid records provided in direct invocation test.",
                extra={"errors": e.errors()},
            )
            # For a test invocation, raising an error is appropriate
            raise ValueError("Invalid test data provided") from e

        # Now we are passing the correct type to the function
        _process_valid_records(records_to_process, {}, context)
        return {"batchItemFailures": []}

    # Path 2: Default path for real SQS messages ---
    else:
        # This block contains your complete, unchanged, and correct SQS processing logic.
        sqs_records: list[dict] = event.get("Records", [])
        if not sqs_records:
            logger.warning("Event did not contain any SQS records. Exiting gracefully.")
            return {"batchItemFailures": []}

        # Log batch processing start with essential stats
        total_s3_records = sum(
            len(json.loads(sqs_record["body"]).get("Records", []))
            for sqs_record in sqs_records
            if sqs_record.get("body")
        )
        
        # Extract S3 keys for debugging purposes
        s3_keys = []
        for sqs_record in sqs_records:
            try:
                if sqs_record.get("body"):
                    s3_event = json.loads(sqs_record["body"])
                    s3_records = s3_event.get("Records", [])
                    for s3_record in s3_records:
                        bucket_name = s3_record.get("s3", {}).get("bucket", {}).get("name", "unknown-bucket")
                        object_key = s3_record.get("s3", {}).get("object", {}).get("key", "unknown-key")
                        s3_keys.append(f"{bucket_name}/{object_key}")
            except (json.JSONDecodeError, KeyError, AttributeError):
                # Skip malformed records for key extraction, they'll be handled in main processing
                continue
        
        logger.info(
            "Starting SQS batch processing",
            extra={
                "sqs_messages": len(sqs_records),
                "total_s3_records": total_s3_records,
                "s3_keys": s3_keys,
                "request_id": context.aws_request_id,
            },
        )

        # --- Setup tracking variables ---
        records_to_process: list[S3EventNotificationRecord] = []
        failed_message_ids: set[str] = set()
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
                    # --- 1. PARSE & VALIDATE ---
                    # This validates structure, types, and runs our security sanitizer.
                    parsed_record = S3EventNotificationRecord.model_validate(s3_record)

                    # --- 2. GENERATE THE UNIQUE IDEMPOTENCY KEY ---
                    # Extract all necessary components from the validated model.
                    original_s3_key = parsed_record.s3.object.original_key
                    s3_version = parsed_record.s3.object.version_id
                    s3_sequencer = parsed_record.s3.object.sequencer

                    # This key is now the single source of truth for this record's uniqueness.
                    idempotency_key = _make_idempotency_key(
                        original_s3_key, s3_version, s3_sequencer
                    )

                    # --- 3. PROCEED WITH PROCESSING ---
                    # Use the idempotency_key itself as the key for our lookup map.
                    # This ensures the logic is perfectly consistent.
                    record_to_message_id_map.setdefault(idempotency_key, set()).add(
                        message_id
                    )

                    # The idempotency payload requires the original s3_object dict
                    # and the unique idempotency key we just generated.
                    payload = {
                        "idempotency_key": idempotency_key,
                        "s3_object": s3_record["s3"]["object"],
                    }
                    _process_record_idempotently(data=payload)

                    # Append the parsed Pydantic object for downstream processing.
                    records_to_process.append(parsed_record)

                except IdempotencyItemAlreadyExistsError:
                    metrics.add_metric(
                        name="FailedIdempotencyChecks", unit=MetricUnit.Count, value=1
                    )
                    logger.info(
                        "Skipping duplicate S3 object.",
                        extra={"idempotency_key": idempotency_key},
                    )
                # Catch Pydantic's validation error instead of our custom ones
                except pydantic.ValidationError as e:
                    metrics.add_metric(
                        name="InvalidS3Records", unit=MetricUnit.Count, value=1
                    )
                    logger.warning(
                        "Invalid S3 record failed validation.",
                        extra={
                            "messageId": message_id,
                            "validation_errors": e.errors(),
                        },
                    )
                    failed_message_ids.add(message_id)
                except Exception as e:
                    metrics.add_metric(
                        name="UnexpectedRecordErrors", unit=MetricUnit.Count, value=1
                    )
                    logger.exception(
                        "Unexpected error processing S3 record.",
                        extra={
                            "messageId": message_id,
                            "error_type": type(e).__name__,
                        },
                    )
                    failed_message_ids.add(message_id)

        # --- 2. Log idempotency filtering results and exit if no valid records ---
        duplicates_count = total_s3_records - len(records_to_process) - len(failed_message_ids)
        logger.info(
            "Idempotency filtering completed",
            extra={
                "total_s3_records": total_s3_records,
                "new_records": len(records_to_process),
                "duplicates_skipped": duplicates_count,
                "validation_failures": len(failed_message_ids),
            },
        )

        if not records_to_process:
            logger.info("No new records to process after filtering.")
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

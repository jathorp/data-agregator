# src/data_aggregator/app.py

import json
import os
import time
from typing import Any, Dict, List, cast

import boto3
import requests
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools.utilities.typing import LambdaContext

from .clients import CircuitBreakerClient, DynamoDBClient, NiFiClient, S3Client
from .core import process_and_deliver_batch

# -----------------------------------------------------------------------------
# Global Scope: Initialization & Configuration
# -----------------------------------------------------------------------------
logger = Logger(service="data-aggregator")
tracer = Tracer(service="data-aggregator")
processor = BatchProcessor(event_type=EventType.SQS)
secrets_provider = SecretsProvider()

# Configuration from environment variables
## REFINED: Made TTL for idempotency configurable via an environment variable.
IDEMPOTENCY_TABLE = os.environ["IDEMPOTENCY_TABLE_NAME"]
IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7")) * 86400
DYNAMODB_TTL_ATTRIBUTE = os.environ.get("DYNAMODB_TTL_ATTRIBUTE", "ttl")
ARCHIVE_BUCKET = os.environ["ARCHIVE_BUCKET_NAME"]
NIFI_ENDPOINT_URL = os.environ["NIFI_ENDPOINT_URL"]
NIFI_SECRET_ARN = os.environ["NIFI_SECRET_ARN"]
CIRCUIT_BREAKER_TABLE = os.environ["CIRCUIT_BREAKER_TABLE_NAME"]

# Service Client Initializations
s3_client_wrapper = S3Client(s3_client=boto3.client("s3"))
dynamodb_client_wrapper = DynamoDBClient(
    dynamo_client=boto3.client("dynamodb"),
    table_name=IDEMPOTENCY_TABLE,
    ttl_attribute=DYNAMODB_TTL_ATTRIBUTE,
)
## REFINED: Assumes CircuitBreakerClient has a `get_state()` method as per prior recommendations.
circuit_breaker_client = CircuitBreakerClient(
    dynamo_client=boto3.client("dynamodb"),
    table_name=CIRCUIT_BREAKER_TABLE,
)
http_session = requests.Session()

## REFINED: Added a simple custom exception for clarity in error handling.
class SQSBatchProcessingError(Exception):
    """Custom exception for batch-level processing failures."""
    pass


# -----------------------------------------------------------------------------
# 1. Record-level handler
# -----------------------------------------------------------------------------
@tracer.capture_method
def record_handler(record: SQSRecord) -> Dict[str, Any]:
    """Processes one SQS message, handling format errors and idempotency."""
    try:
        s3_event_body = json.loads(record.body)
        s3_record = s3_event_body["Records"][0]
        object_key = s3_record["s3"]["object"]["key"]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Malformed SQS message, will be marked as failed.", extra={"record": record.body})
        raise ValueError("Malformed SQS message body") from exc

    ttl = int(time.time()) + IDEMPOTENCY_TTL_SECONDS
    if dynamodb_client_wrapper.check_and_set_idempotency(object_key, ttl):
        logger.info("New object key detected, adding to batch.", extra={"key": object_key})
        return s3_record
    else:
        logger.warning("Duplicate object key detected, skipping.", extra={"key": object_key})
        return {}


# -----------------------------------------------------------------------------
# 2. Main Lambda handler
# -----------------------------------------------------------------------------
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    """Main entry point orchestrating the two-stage processing."""

    # --- Stage 1: Process individual messages ---
    with processor(records=event["Records"], handler=record_handler):
        pass

    successful_s3_records: List[Dict[str, Any]] = [
        cast(Dict[str, Any], record.result)
        for record in processor.success_messages
        if record.result
    ]

    if not successful_s3_records:
        logger.info("No new, valid records to process in this batch.")
        return processor.response() # Return any parsing/idempotency failures

    # --- Stage 2: Process the aggregated batch ---
    breaker_state = circuit_breaker_client.get_state()
    if breaker_state == "OPEN":
        logger.error("Circuit breaker is OPEN. Failing entire batch immediately.")
        raise SQSBatchProcessingError("Circuit Breaker is open")

    # Fetch NiFi credentials.
    nifi_creds = secrets_provider.get(NIFI_SECRET_ARN, transform="json")

    # REFINED: Dynamically calculate read timeout based on remaining Lambda time for resilience.
    remaining_time_ms = context.get_remaining_time_in_millis()
    read_timeout = max((remaining_time_ms / 1000) - 8, 5) # Leave an 8-second buffer

    nifi_client_wrapper = NiFiClient(
        session=http_session,
        endpoint_url=NIFI_ENDPOINT_URL,
        auth=(nifi_creds["username"], nifi_creds["password"]),
    )

    records_to_process = successful_s3_records
    if breaker_state == "HALF_OPEN":
        logger.warning("Circuit breaker is HALF_OPEN. Attempting single-record test delivery.")
        records_to_process = successful_s3_records[:1]

    try:
        archive_key = f"bundle-{context.aws_request_id}.gz"
        content_hash = process_and_deliver_batch(
            records=records_to_process,
            s3_client=s3_client_wrapper,
            nifi_client=nifi_client_wrapper,
            archive_bucket=ARCHIVE_BUCKET,
            archive_key=archive_key,
            read_timeout=int(read_timeout),
        )
        logger.info("Successfully delivered batch.", extra={"hash": content_hash, "archive_key": archive_key})
        circuit_breaker_client.record_success()

        # If HALF-OPEN test succeeded, we must manually build the failure response
        # to return the other messages to the queue for the next invocation.
        if breaker_state == "HALF_OPEN" and len(successful_s3_records) > 1:
            logger.info("Test record succeeded. Manually constructing response to return remaining records to SQS.")

            ## CORRECTED: 1. Get initial failures using the processor's public method.
            # The .response() method returns the correctly formatted dict for parsing failures.
            initial_failures = processor.response().get("batchItemFailures", [])

            # Create a new list containing the initial failures.
            all_failed_items = list(initial_failures)

            ## CORRECTED: 2. Append the items to be retried from the current batch.
            # These are all the successfully parsed messages, except the first one we processed as a test.
            for record_to_retry in processor.success_messages[1:]:
                all_failed_items.append({"itemIdentifier": record_to_retry.message_id})

            # Return the final, combined list of failures. This structure is correct.
            if all_failed_items:
                return {"batchItemFailures": all_failed_items}


    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error("Request to NiFi timed out or connection failed.", exc_info=True)
        circuit_breaker_client.record_failure()
        raise SQSBatchProcessingError("Downstream connection error") from e

    # If we get here, it means the entire batch (in either CLOSED or HALF-OPEN single-record mode) was successful.
    # We can rely on the processor's default response, which will be empty if all parsing was successful.
    return processor.response()
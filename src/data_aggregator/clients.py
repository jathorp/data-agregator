# src/data_aggregator/clients.py

import logging
import time
from typing import Any, BinaryIO, Tuple, Union, Optional

import requests
from botocore.exceptions import ClientError
from aws_lambda_powertools.metrics import Metrics

# Get a logger instance for this module.
logger = logging.getLogger(__name__)


class S3Client:
    """A wrapper for S3 client operations, optimized for streams."""

    def __init__(self, s3_client: Any):
        self._client = s3_client

    def get_file_content_stream(self, bucket: str, key: str) -> Any:
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"]

    def upload_gzipped_bundle(
        self, bucket: str, key: str, file_obj: BinaryIO, content_hash: str
    ):
        self._client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=bucket,
            Key=key,
            ExtraArgs={"Metadata": {"x-content-sha256": content_hash}},
        )


class DynamoDBClient:
    """A wrapper for DynamoDB client operations."""

    def __init__(self, dynamo_client: Any, table_name: str, ttl_attribute: str):
        self._client = dynamo_client
        self._table_name = table_name
        self._ttl_attribute = ttl_attribute

    def check_and_set_idempotency(self, object_key: str, ttl: int) -> bool:
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item={
                    "object_key": {"S": object_key},
                    self._ttl_attribute: {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(object_key)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise


class NiFiClient:
    """A wrapper for making HTTP requests to the NiFi endpoint."""

    def __init__(
        self,
        session: requests.Session,
        endpoint_url: str,
        auth: Tuple[str, str],
        connect_timeout: int = 5,
    ):
        self._session = session
        self._endpoint_url = endpoint_url
        self._auth = auth
        self._connect_timeout = connect_timeout

    def post_bundle(
        self, data: Union[bytes, BinaryIO], content_hash: str, read_timeout: int
    ):
        headers = {
            "Content-Type": "application/gzip",
            "Content-Encoding": "gzip",
            "X-Content-SHA256": content_hash,
        }
        response = self._session.post(
            self._endpoint_url,
            data=data,
            headers=headers,
            auth=self._auth,
            timeout=(self._connect_timeout, read_timeout),
        )
        response.raise_for_status()


class CircuitBreakerClient:
    """
    Manages the state of the circuit breaker in DynamoDB.
    This implementation is self-healing, automatically transitioning from OPEN to
    HALF_OPEN after a configured timeout period.
    """

    def __init__(
        self,
        dynamo_client: Any,
        table_name: str,
        metrics: Metrics,
        failure_threshold: int,
        open_duration_seconds: int,
        service_name: str = "NiFi",
    ):
        self._client = dynamo_client
        self._table_name = table_name
        self._metrics = metrics
        self._service_name = service_name
        self._failure_threshold = failure_threshold
        self._open_duration_seconds = open_duration_seconds

    def get_state(self) -> str:
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key={"service_name": {"S": self._service_name}},
                ConsistentRead=True,
            )
            item = response.get("Item")
            if not item:
                return "CLOSED"

            state = item.get("state", {}).get("S", "CLOSED")
            if state == "OPEN":
                last_updated = int(item.get("last_updated", {}).get("N", "0"))
                if time.time() - last_updated > self._open_duration_seconds:
                    logger.warning(
                        "Circuit breaker timeout expired. Attempting to transition from OPEN to HALF_OPEN."
                    )
                    try:
                        self._client.update_item(
                            TableName=self._table_name,
                            Key={"service_name": {"S": self._service_name}},
                            UpdateExpression="SET #S = :new_state, #LU = :now",
                            ConditionExpression="#S = :old_state",
                            ExpressionAttributeNames={
                                "#S": "state",
                                "#LU": "last_updated",
                            },
                            ExpressionAttributeValues={
                                ":new_state": {"S": "HALF_OPEN"},
                                ":old_state": {"S": "OPEN"},
                                ":now": {"N": str(int(time.time()))},
                            },
                        )
                        return "HALF_OPEN"
                    except ClientError as e:
                        if (
                            e.response["Error"]["Code"]
                            == "ConditionalCheckFailedException"
                        ):
                            logger.warning(
                                "Failed to transition to HALF_OPEN; state was changed by another process. Re-fetching."
                            )
                            return self.get_state()
                        raise
                else:
                    return "OPEN"
            else:
                return state

        except ClientError as e:
            logger.error(
                "Error getting circuit breaker state. Defaulting to CLOSED.", exc_info=e
            )
            return "CLOSED"

    def record_success(self):
        """
        Conditionally resets the circuit from HALF_OPEN to CLOSED.
        This is an atomic operation to prevent race conditions.
        """
        logger.info("Recording successful delivery. Attempting to close circuit.")
        try:
            # Use a conditional update_item for a more robust reset
            # This ensures we only close a circuit that was in the HALF_OPEN state,
            # preventing a slow success from overwriting a more recent failure.
            self._client.update_item(
                TableName=self._table_name,
                Key={"service_name": {"S": self._service_name}},
                UpdateExpression="SET #S = :closed_state, failure_count = :zero",
                ConditionExpression="#S = :half_open_state",
                ExpressionAttributeNames={"#S": "state"},
                ExpressionAttributeValues={
                    ":closed_state": {"S": "CLOSED"},
                    ":zero": {"N": "0"},
                    ":half_open_state": {"S": "HALF_OPEN"},
                },
            )
            logger.info("Successfully transitioned circuit from HALF_OPEN to CLOSED.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "record_success called, but circuit was not in HALF_OPEN state. No action taken."
                )
            else:
                logger.error("Error trying to reset circuit breaker", exc_info=True)
                raise

    def record_failure(self):
        """Increments the failure count and potentially opens the circuit."""
        logger.warning("Recording delivery failure. Incrementing failure count.")
        current_state_before_update = self.get_state()

        try:
            # Atomically increments the failure counter in DynamoDB.
            response = self._client.update_item(
                TableName=self._table_name,
                Key={"service_name": {"S": self._service_name}},
                UpdateExpression="ADD failure_count :inc",
                ExpressionAttributeValues={":inc": {"N": "1"}},
                ReturnValues="UPDATED_NEW",
            )
            new_count = int(response["Attributes"]["failure_count"]["N"])

            logger.info(f"Updated failure count to {new_count}.")
            if new_count >= self._failure_threshold:
                logger.error(
                    f"Failure threshold of {self._failure_threshold} reached. Opening circuit."
                )
                self.set_state("OPEN", previous_state=current_state_before_update)
        except ClientError as e:
            logger.error(
                "Failed to update failure count. Setting state to OPEN as a fallback.",
                exc_info=e,
            )
            self.set_state("OPEN", previous_state=current_state_before_update)

    def set_state(self, state: str, previous_state: Optional[str] = None):
        """
        A helper method to set a specific state in DynamoDB.
        Adds a metric if the circuit transitions to OPEN.
        """
        try:
            if previous_state is None:
                previous_state = self.get_state()

            self._client.put_item(
                TableName=self._table_name,
                Item={
                    "service_name": {"S": self._service_name},
                    "state": {"S": state},
                    "failure_count": {"N": "0"},
                    "last_updated": {"N": str(int(time.time()))},
                },
            )

            if state == "OPEN" and previous_state != "OPEN":
                logger.warning("Circuit breaker transitioned to OPEN. Adding metric.")
                self._metrics.add_metric(
                    name="CircuitBreakerOpen", unit="Count", value=1
                )
        except ClientError as e:
            logger.error(f"Failed to set circuit breaker state to {state}", exc_info=e)

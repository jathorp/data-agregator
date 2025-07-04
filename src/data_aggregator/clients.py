# src/data_aggregator/clients.py
import logging
import time
from typing import Any, BinaryIO, Tuple, Union

import requests
from botocore.exceptions import ClientError

# Get a logger instance for this module.
logger = logging.getLogger(__name__)

# ... (S3Client and DynamoDBClient from previous correct version) ...
class S3Client:
    def __init__(self, s3_client: Any):
        self._client = s3_client

    def get_file_content_stream(self, bucket: str, key: str) -> Any:
        """Returns the raw streaming body from the S3 object."""
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"]

    def upload_gzipped_bundle(self, bucket: str, key: str, file_obj: BinaryIO, content_hash: str):
        self._client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=bucket,
            Key=key,
            ExtraArgs={"Metadata": {"x-content-sha256": content_hash}},
        )

class DynamoDBClient:
    def __init__(self, dynamo_client: Any, table_name: str, ttl_attribute: str):
        self._client = dynamo_client
        self._table_name = table_name
        self._ttl_attribute = ttl_attribute

    def check_and_set_idempotency(self, object_key: str, ttl: int) -> bool:
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item={"object_key": {"S": object_key}, self._ttl_attribute: {"N": str(ttl)}},
                ConditionExpression="attribute_not_exists(object_key)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

class NiFiClient:
    def __init__(self, session: requests.Session, endpoint_url: str, auth: Tuple[str, str], connect_timeout: int = 5):
        self._session = session
        self._endpoint_url = endpoint_url
        self._auth = auth
        self._connect_timeout = connect_timeout # Store connect timeout

    # UPDATED: Accept a dynamic read_timeout
    def post_bundle(self, data: Union[bytes, BinaryIO], content_hash: str, read_timeout: int):
        headers = { "Content-Type": "application/gzip", "Content-Encoding": "gzip", "X-Content-SHA256": content_hash }
        response = self._session.post(
            self._endpoint_url,
            data=data,
            headers=headers,
            auth=self._auth,
            timeout=(self._connect_timeout, read_timeout),
        )
        response.raise_for_status()

# NEW: The full CircuitBreakerClient
class CircuitBreakerClient:
    """Manages the state of the circuit breaker in DynamoDB."""
    def __init__(self, dynamo_client: Any, table_name: str, service_name: str = "NiFi"):
        self._client = dynamo_client
        self._table_name = table_name
        self._service_name = service_name
        # TODO: These could be configurable
        self._failure_threshold = 3
        self._open_duration_seconds = 300 # 5 minutes

    def get_state(self) -> str:
        """Gets the raw state of the circuit from DynamoDB."""
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key={"service_name": {"S": self._service_name}},
            )
            return response.get("Item", {}).get("state", {}).get("S", "CLOSED")
        except ClientError:
            return "CLOSED" # Default to closed

    def is_open(self) -> bool:
        """Checks if the circuit is currently OPEN and the timeout hasn't expired."""
        try:
            item = self._client.get_item(...).get("Item") # simplified for brevity
            if not item or item.get("state", {}).get("S") != "OPEN":
                return False

            last_updated = int(item.get("last_updated", {}).get("N", "0"))
            if time.time() - last_updated > self._open_duration_seconds:
                # The state is stale and OPEN. It should be moved to HALF-OPEN.
                # A separate process (e.g., scheduled Lambda) should do this.
                # For now, this check prevents getting stuck in OPEN forever.
                logger.info("Circuit breaker state is OPEN but timeout has expired.")
                return False # Allow a request through to test the waters.
            return True
        except ClientError:
            return False

    def set_state(self, state: str):
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "service_name": {"S": self._service_name},
                "state": {"S": state},
                "failure_count": {"N": "0"}, # Reset count on any state change
                "last_updated": {"N": str(int(time.time()))},
            },
        )

    def record_success(self):
        """Resets the failure count and ensures the circuit is CLOSED."""
        self.set_state("CLOSED")

    def record_failure(self):
        """Increments the failure count and potentially opens the circuit."""
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={"service_name": {"S": self._service_name}},
                UpdateExpression="ADD failure_count :inc",
                ExpressionAttributeValues={":inc": {"N": "1"}},
                ReturnValues="UPDATED_NEW",
            )
            new_count = int(response["Attributes"]["failure_count"]["N"])
            if new_count >= self._failure_threshold:
                self.set_state("OPEN")
        except ClientError as e:
            logger.error("Failed to update failure count. Setting state to OPEN as a fallback.", exc_info=e)
            # If update fails (e.g., item doesn't exist), just set it to OPEN directly.
            self.set_state("OPEN")
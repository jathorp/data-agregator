# src/data_aggregator/clients.py

import logging
from typing import Any, BinaryIO

from botocore.exceptions import ClientError

# Get a logger instance for this module.
logger = logging.getLogger(__name__)


class S3Client:
    """A wrapper for S3 client operations, optimized for streams."""

    def __init__(self, s3_client: Any):
        self._client = s3_client

    def get_file_content_stream(self, bucket: str, key: str) -> Any:
        """Gets a file from S3 as a streaming body."""
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"]

    def upload_gzipped_bundle(
            self, bucket: str, key: str, file_obj: BinaryIO, content_hash: str
    ):
        """Uploads a file-like object to S3 with custom metadata."""
        self._client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=bucket,
            Key=key,
            ExtraArgs={"Metadata": {"content-sha256": content_hash}},
        )


class DynamoDBClient:
    """A wrapper for DynamoDB client operations."""

    def __init__(self, dynamo_client: Any, table_name: str, ttl_attribute: str):
        self._client = dynamo_client
        self._table_name = table_name
        self._ttl_attribute = ttl_attribute

    def check_and_set_idempotency(self, object_key: str, ttl: int) -> bool:
        """
        Attempts to write a new object key to the idempotency table.
        Returns True if the write succeeds (key is new), False if it fails
        due to the key already existing.
        """
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

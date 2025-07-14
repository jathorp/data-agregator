# src/data_aggregator/clients.py

"""
Client wrappers for interacting with AWS services (S3 and DynamoDB).

These classes provide a clean, abstracted interface over raw boto3 clients,
making the core application logic easier to read, test, and maintain. They
incorporate best practices like typed interfaces and efficient API usage.
"""

import logging
from typing import Any, BinaryIO, TYPE_CHECKING, Optional

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client as S3ClientType
    from mypy_boto3_s3.type_defs import CopySourceTypeDef
    from mypy_boto3_dynamodb.client import DynamoDBClient as DynamoDBClientType

logger = logging.getLogger(__name__)


class S3Client:
    """
    A wrapper for S3 client operations, focused on streaming data and security.
    """

    def __init__(self, s3_client: "S3ClientType", kms_key_id: Optional[str] = None):
        """
        Initializes the S3Client.

        Args:
            s3_client: A typed boto3 S3 client.
            kms_key_id: Optional KMS key ID for server-side encryption.
        """
        self._client = s3_client
        self._kms_key_id = kms_key_id
        if self._kms_key_id:
            logger.debug(
                "S3Client initialized with SSE-KMS enabled.",
                extra={"kms_key_id": self._kms_key_id},
            )

    def get_file_content_stream(self, bucket: str, key: str) -> Any:
        """Gets an object from S3 as a streaming body."""
        logger.debug(
            "Requesting S3 object stream", extra={"bucket": bucket, "key": key}
        )
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"]

    def upload_gzipped_bundle(
        self, bucket: str, key: str, file_obj: BinaryIO, content_hash: str
    ):
        """Uploads a file-like object to S3 via a managed, streaming upload."""
        extra_args = {
            "Metadata": {"content-sha256": content_hash},
            "ContentEncoding": "gzip",
            "ContentType": "application/gzip",
        }
        if self._kms_key_id:
            extra_args.update(
                {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self._kms_key_id}
            )
        logger.info(
            "Uploading bundle",
            extra={"bucket": bucket, "key": key, "kms_enabled": bool(self._kms_key_id)},
        )
        self._client.upload_fileobj(
            Fileobj=file_obj, Bucket=bucket, Key=key, ExtraArgs=extra_args
        )
        logger.debug(
            "Upload (PUT) completed successfully", extra={"bucket": bucket, "key": key}
        )


class DynamoDBClient:
    """
    Wrapper for DynamoDB client operations, tailored for idempotency checks.
    """

    def __init__(
        self, dynamo_client: "DynamoDBClientType", table_name: str, ttl_attribute: str
    ):
        """Initializes the DynamoDBClient."""
        self._client = dynamo_client
        self._table_name = table_name
        self._ttl_attribute = ttl_attribute

    def check_and_set_idempotency(
        self, idempotency_key: str, original_object_key: str, ttl: int
    ) -> bool:
        """
        Atomically writes a hashed key to the idempotency table if it doesn't exist.

        This uses a ConditionExpression to ensure the write only succeeds if the
        primary key is new, which is the core of the idempotency logic.

        Args:
            idempotency_key: The SHA256 hash of the object key (the Partition Key).
            original_object_key: The actual S3 object key (stored for reference).
            ttl: The Unix timestamp when the record should expire.

        Returns:
            True if the key was new and written, False if it was a duplicate.
        """
        logger.debug(
            "Checking idempotency key in DynamoDB",
            extra={"idempotency_key": idempotency_key},
        )
        try:
            # NOTE: The DynamoDB table's primary key must be 'idempotency_key'.
            self._client.put_item(
                TableName=self._table_name,
                Item={
                    "idempotency_key": {"S": idempotency_key},
                    "object_key": {"S": original_object_key},
                    self._ttl_attribute: {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(idempotency_key)",
            )
            logger.debug(
                "Idempotency key was new", extra={"idempotency_key": idempotency_key}
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.debug(
                    "Duplicate key detected", extra={"idempotency_key": idempotency_key}
                )
                return False
            logger.error(
                "Unexpected DynamoDB error during idempotency check", exc_info=True
            )
            raise

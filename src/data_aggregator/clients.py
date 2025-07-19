# src/data_aggregator/clients.py

"""
Client wrappers for interacting with AWS services (S3 and DynamoDB).

These classes provide a clean, abstracted interface over raw boto3 clients,
making the core application logic easier to read, test, and maintain. They
incorporate best practices like typed interfaces and efficient API usage.
"""

import logging
from typing import Any, BinaryIO, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client as S3ClientType

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

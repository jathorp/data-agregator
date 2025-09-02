# src/data_aggregator/clients.py

"""
Client wrappers for interacting with AWS services (S3 and DynamoDB).

These classes provide a clean, abstracted interface over raw boto3 clients,
making the core application logic easier to read, test, and maintain. They
incorporate best practices like typed interfaces and efficient API usage.
"""

import logging
from typing import BinaryIO, TYPE_CHECKING, cast

from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

from .exceptions import (
    S3AccessDeniedError,
    S3ObjectNotFoundError,
    S3ThrottlingError,
    S3TimeoutError,
    BundleCreationError,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client as S3ClientType

logger = logging.getLogger(__name__)


class S3Client:
    """
    A wrapper for S3 client operations, focused on streaming data and security.
    """

    def __init__(self, s3_client: "S3ClientType", kms_key_id: str | None = None):
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

    def get_file_content_stream(self, bucket: str, key: str) -> BinaryIO:
        """
        Retrieves an S3 object's body as a file-like streaming object.
        Raises specific S3 exceptions based on the error type.
        """
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            return cast(BinaryIO, response["Body"])
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            # Map boto3 error codes to our specific exception types
            if error_code == "NoSuchKey":
                raise S3ObjectNotFoundError(
                    bucket=bucket,
                    key=key,
                    context={
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            elif error_code == "AccessDenied":
                raise S3AccessDeniedError(
                    bucket=bucket,
                    key=key,
                    context={
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            elif error_code in [
                "Throttling",
                "ThrottlingException",
                "RequestLimitExceeded",
            ]:
                raise S3ThrottlingError(
                    f"S3 request throttled: {error_message}",
                    error_code="S3_THROTTLING",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            elif error_code in ["RequestTimeout", "RequestTimeoutException"]:
                raise S3TimeoutError(
                    f"S3 request timed out: {error_message}",
                    error_code="S3_TIMEOUT",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            else:
                # For other client errors, wrap in a generic S3 error
                raise BundleCreationError(
                    f"S3 client error: {error_message}",
                    error_code="S3_CLIENT_ERROR",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
        except ReadTimeoutError as e:
            raise S3TimeoutError(
                "S3 read timeout while retrieving object",
                error_code="S3_READ_TIMEOUT",
                context={"bucket": bucket, "key": key, "timeout_error": str(e)},
            ) from e
        except EndpointConnectionError as e:
            raise S3TimeoutError(
                "S3 endpoint connection error",
                error_code="S3_CONNECTION_ERROR",
                context={"bucket": bucket, "key": key, "connection_error": str(e)},
            ) from e

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

        try:
            self._client.upload_fileobj(
                Fileobj=file_obj, Bucket=bucket, Key=key, ExtraArgs=extra_args
            )
            logger.debug(
                "Upload (PUT) completed successfully",
                extra={"bucket": bucket, "key": key},
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            # Map boto3 error codes to our specific exception types
            if error_code == "AccessDenied":
                raise S3AccessDeniedError(
                    bucket=bucket,
                    key=key,
                    context={
                        "content_hash": content_hash,
                        "kms_enabled": bool(self._kms_key_id),
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            elif error_code in [
                "Throttling",
                "ThrottlingException",
                "RequestLimitExceeded",
            ]:
                raise S3ThrottlingError(
                    f"S3 upload request throttled: {error_message}",
                    error_code="S3_UPLOAD_THROTTLING",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "content_hash": content_hash,
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            elif error_code in ["RequestTimeout", "RequestTimeoutException"]:
                raise S3TimeoutError(
                    f"S3 upload timed out: {error_message}",
                    error_code="S3_UPLOAD_TIMEOUT",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "content_hash": content_hash,
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
            else:
                # For other client errors, wrap in bundle creation error
                raise BundleCreationError(
                    f"Failed to upload bundle to S3: {error_message}",
                    error_code="S3_UPLOAD_ERROR",
                    context={
                        "bucket": bucket,
                        "key": key,
                        "content_hash": content_hash,
                        "kms_enabled": bool(self._kms_key_id),
                        "aws_error_code": error_code,
                        "aws_error_message": error_message,
                    },
                ) from e
        except ReadTimeoutError as e:
            raise S3TimeoutError(
                "S3 upload read timeout",
                error_code="S3_UPLOAD_READ_TIMEOUT",
                context={
                    "bucket": bucket,
                    "key": key,
                    "content_hash": content_hash,
                    "timeout_error": str(e),
                },
            ) from e
        except EndpointConnectionError as e:
            raise S3TimeoutError(
                "S3 upload connection error",
                error_code="S3_UPLOAD_CONNECTION_ERROR",
                context={
                    "bucket": bucket,
                    "key": key,
                    "content_hash": content_hash,
                    "connection_error": str(e),
                },
            ) from e

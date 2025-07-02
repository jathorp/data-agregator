"""
Factory module for creating boto3 clients with type support.

This is the DI hub of the application: real clients in Lambda,
moto-mocked clients in tests.
"""

import logging
import os
from typing import cast

import boto3
from botocore.config import Config, _RetryDict

from mypy_boto3_s3 import S3Client
from mypy_boto3_sqs import SQSClient
from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
from mypy_boto3_secretsmanager import SecretsManagerClient


logger = logging.getLogger(__name__)

# Shared retry config
BOTO_CONFIG_RETRYABLE = Config(
    retries=cast(_RetryDict, {"max_attempts": 5, "mode": "adaptive"})
)


def get_boto_clients() -> tuple[
    S3Client,
    SQSClient,
    DynamoDBServiceResource,
    SecretsManagerClient,
]:
    """Return S3, SQS, DynamoDB and Secrets Manager clients/resources."""

    aws_region = os.environ.get("AWS_REGION")
    if not aws_region:
        logger.warning("AWS_REGION not set; boto3 will resolve a default region.")

    if os.environ.get("USE_MOTO"):
        logger.info("MOTO ENABLED: returning mocked AWS clients.")

    # `boto3` returns generic clients. We use `cast` to inform the type checker
    # of the specific client type we know we are creating.
    s3_client = cast(S3Client, boto3.client("s3", region_name=aws_region))
    sqs_client = cast(SQSClient, boto3.client("sqs", region_name=aws_region))
    dynamodb_resource = cast(
        DynamoDBServiceResource, boto3.resource("dynamodb", region_name=aws_region)
    )
    secretsmanager_client = cast(
        SecretsManagerClient, boto3.client("secretsmanager", region_name=aws_region)
    )

    return (
        s3_client,
        sqs_client,
        dynamodb_resource,
        secretsmanager_client,
    )

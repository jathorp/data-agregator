"""
Factory module for creating boto3 clients with type support.

This is the DI hub of the application: real clients in Lambda,
moto-mocked clients in tests.
"""

import logging
import os
from typing import cast

import boto3
from botocore.config import Config
from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
from mypy_boto3_s3 import S3Client
from mypy_boto3_secretsmanager import SecretsManagerClient
from mypy_boto3_sqs import SQSClient

logger = logging.getLogger(__name__)

BOTO_CONFIG_RETRYABLE = Config(
    retries={'max_attempts': 5, 'mode': 'adaptive'}  # type: ignore[arg-type]
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

    # FIX: Moto safety guardrail now checks for any env starting with "prod".
    if os.environ.get("USE_MOTO"):
        environment = os.environ.get("ENVIRONMENT", "dev")
        if environment.startswith("prod"):
            raise EnvironmentError(
                "FATAL: USE_MOTO cannot be enabled in a production environment."
            )
        logger.info("MOTO ENABLED: returning mocked AWS clients.")

    # The region is now handled by the session, simplifying client creation.
    session = boto3.Session(region_name=aws_region)

    s3_client = cast(
        S3Client, session.client("s3", config=BOTO_CONFIG_RETRYABLE)
    )
    sqs_client = cast(
        SQSClient, session.client("sqs", config=BOTO_CONFIG_RETRYABLE)
    )
    dynamodb_resource = cast(
        DynamoDBServiceResource,
        session.resource("dynamodb", config=BOTO_CONFIG_RETRYABLE),
    )
    secretsmanager_client = cast(
        SecretsManagerClient,
        session.client("secretsmanager", config=BOTO_CONFIG_RETRYABLE),
    )

    return (
        s3_client,
        sqs_client,
        dynamodb_resource,
        secretsmanager_client,
    )
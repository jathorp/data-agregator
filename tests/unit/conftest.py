# tests/unit/conftest.py

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_REGION"] = "eu-west-2"

@pytest.fixture(autouse=True)
def mock_app_environment():
    """Sets up all necessary environment variables for app.py"""
    os.environ["IDEMPOTENCY_TABLE_NAME"] = "test-idempotency-table"
    os.environ["CIRCUIT_BREAKER_TABLE_NAME"] = "test-circuit-breaker-table"
    os.environ["ARCHIVE_BUCKET_NAME"] = "test-archive-bucket"
    os.environ["NIFI_ENDPOINT_URL"] = "https://test.nifi.endpoint"
    os.environ["NIFI_SECRET_ARN"] = "arn:aws:secretsmanager:eu-west-2:12345:secret:test"
    os.environ["DYNAMODB_TTL_ATTRIBUTE"] = "ttl"
    os.environ["IDEMPOTENCY_TTL_DAYS"] = "7"
    os.environ["AWS_REGION"] = "eu-west-2" # Explicitly set the region

@pytest.fixture(scope="function")
def mocked_s3(aws_credentials):
    """Fixture to mock S3 interactions."""
    with mock_aws():
        yield boto3.client("s3", region_name="eu-west-2")


@pytest.fixture(scope="function")
def mocked_dynamodb(aws_credentials):
    """Fixture to mock DynamoDB interactions."""
    with mock_aws():
        yield boto3.client("dynamodb", region_name="eu-west-2")

# Add more fixtures for SQS, Secrets Manager as needed...
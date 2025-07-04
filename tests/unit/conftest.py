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
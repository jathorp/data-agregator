"""
Shared fixtures for unit tests.
"""

from __future__ import annotations

import json
import os
import types
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="session", autouse=True)
def _env_vars():
    """
    Ensures a deterministic environment for every test run.
    Overwrite *only* the variables needed by the handler.
    """
    original = os.environ.copy()
    os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "data-aggregator-test")
    os.environ.setdefault("POWERTOOLS_LOG_LEVEL", "INFO")
    yield
    os.environ.clear()
    os.environ.update(original)


# ---------- Minimal, realistic dummy events ---------- #
@pytest.fixture
def sqs_event() -> dict:
    """One SQS record that wraps a *single* S3 PUT event."""
    s3_event = {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": "eu-west-1",
                "eventTime": datetime.now(timezone.utc).isoformat(),
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": "source-bucket"},
                    "object": {"key": "input/file1.json", "size": 123},
                },
            }
        ]
    }

    return {
        "Records": [
            {
                "messageId": str(uuid.uuid4()),
                "receiptHandle": "ignore",
                "body": json.dumps(s3_event),  # what the lambda really sees
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "dummy",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:eu-west-1:000000000000:dummy",
                "awsRegion": "eu-west-1",
            }
        ]
    }


@pytest.fixture
def lambda_context():
    """A *very* small stand-in for the LambdaContext object."""
    return types.SimpleNamespace(
        aws_request_id="req-" + uuid.uuid4().hex,
        invoked_function_arn="arn:aws:lambda:eu-west-1:000000000000:function:dummy",
        get_remaining_time_in_millis=lambda: 30000,
    )

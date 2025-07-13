# src/app.py          <-- keep it at the top level of the ZIP

"""
Minimal end-to-end BatchProcessor smoke test.
No real S3 or DynamoDB calls yet!
"""
import json
from typing import Any, Dict, List

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.batch.types import (
    PartialItemFailureResponse,
    PartialItemFailures,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

logger  = Logger(service="smoke-batch")
tracer  = Tracer(service="smoke-batch")
metrics = Metrics(namespace="SmokeBatch", service="smoke-batch")
processor = BatchProcessor(event_type=EventType.SQS)

# ────────────────────────────────────────────────────────────
class DummyDynamoDBClient:
    """Does nothing except pretend every key is new."""
    def check_and_set_idempotency(self, key, expiry):
        logger.info("Pretending to write key %s with expiry %s", key, expiry)
        return True

dummy_ddb = DummyDynamoDBClient()

# ────────────────────────────────────────────────────────────
def record_handler(record: SQSRecord) -> Dict[str, Any]:
    body = json.loads(record.body)
    logger.info("Processing dummy record", extra={"body": body})
    dummy_ddb.check_and_set_idempotency("some-id", 0)
    return {"ok": True}

# ────────────────────────────────────────────────────────────
@tracer.capture_lambda_handler
@logger.inject_lambda_context
@metrics.log_metrics
def handler(event: Dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    with processor(records=event["Records"], handler=record_handler):
        pass
    return processor.response()

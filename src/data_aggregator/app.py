# src/app.py          <-- keep it at the top level of the ZIP

from aws_lambda_powertools import Logger
from data_aggregator.core import health_check

logger = Logger(service="smoke-test")

def handler(event, context):
    logger.info("Powertools import succeeded!", extra={"event": event})
    return {"core_says": health_check()}

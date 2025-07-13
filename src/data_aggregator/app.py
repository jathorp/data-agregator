# src/app.py          <-- keep it at the top level of the ZIP

from data_aggregator.core import health_check

def handler(event, context):
    return {"core_says": health_check()}

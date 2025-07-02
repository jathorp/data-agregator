"""
Core business logic for the Data Aggregation Pipeline.

These functions are designed to be "pure" and testable. They receive all
dependencies, including the Powertools logger, from the main handler in app.py,
allowing them to be unit-tested in isolation.
"""
import hashlib
from urllib.parse import unquote

from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

# Import boto3 stubs for full type-safety in function signatures
from mypy_boto3_dynamodb.service_resource import Table


def is_object_unique(
    ddb_table: Table, ttl: int, s3_key: str, message_id: str, logger: Logger
) -> bool:
    """
    Checks for and records the idempotency of a single S3 object key.

    This function uses a DynamoDB conditional write to guarantee that each unique
    S3 object is processed only once. It attempts to write a new item to the
    table with the object's key.

    - If the write succeeds, the object is new and has not been processed before.
    - If the write fails with a 'ConditionalCheckFailedException', it means the
      key already exists in the table, and the object is a duplicate.

    QA Checks for this function:
    - When a new file is processed, a corresponding item should appear in the
      DynamoDB idempotency table. The item's 'ObjectID' should be '{bucket}/{key}'.
    - If the same file is processed again (e.g., via a replayed SQS message),
      the logs should show "Duplicate object key detected," and this function
      should return False.

    Args:
        ddb_table: The boto3 DynamoDB Table resource object for idempotency.
        ttl: The Unix timestamp for when this idempotency record should expire.
        s3_key: The S3 object key to check (e.g., 'path/to/file.txt').
        message_id: The unique ID of the SQS message being processed.
        logger: The Powertools Logger instance for structured logging.

    Returns:
        True if the object key is new (unique).
        False if the object key is a duplicate.
    """
    # The ObjectID is a combination of the bucket and key to ensure it's globally unique.
    # We must unquote the key to handle special characters like spaces (%20).
    object_id = unquote(s3_key)

    # Create a hex hash prefix (e.g., 'a4f1') from the object_id to ensure
    # writes are distributed evenly across DynamoDB's physical partitions.
    hash_prefix = hashlib.sha1(object_id.encode()).hexdigest()[:4]
    sharded_object_id = f"{hash_prefix}#{object_id}"

    try:
        ddb_table.put_item(
            Item={
                # FIX: Use the new sharded key as the partition key.
                "ObjectID": sharded_object_id,
                "ExpiresAt": ttl,
                "SQSMessageID": message_id,
            },
            ConditionExpression="attribute_not_exists(ObjectID)",
        )
        # FIX: Log the sharded key.
        logger.info(f"New unique object key registered: {sharded_object_id}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # FIX: Log the sharded key.
            logger.info(f"Duplicate object key detected: {sharded_object_id}")
            return False
        else:
            logger.exception("Unexpected DynamoDB error during idempotency check.")
            raise

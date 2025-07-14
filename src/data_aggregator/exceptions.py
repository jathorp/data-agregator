# src/data_aggregator/exceptions.py

"""
Shared custom exceptions for the Data Aggregator service.

Centralizing exception definitions in a separate module prevents circular
import errors between other modules that need to raise or catch them.
"""


class SQSBatchProcessingError(Exception):
    """Base class for errors that require the entire batch to be retried by SQS."""


class BundlingTimeoutError(SQSBatchProcessingError):
    """Raised when not enough Lambda time is left to safely create a bundle."""


class BatchTooLargeError(SQSBatchProcessingError):
    """Raised when the sum of input object sizes exceeds the configured limit."""


class TransientDynamoError(SQSBatchProcessingError):
    """Raised for transient DynamoDB issues during the idempotency check."""

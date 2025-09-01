# src/data_aggregator/exceptions.py

"""
Shared custom exceptions for the Data Aggregator service.

Centralizing exception definitions in a separate module prevents circular
import errors between other modules that need to raise or catch them.

Exception Hierarchy:
- DataAggregatorError (base)
  - RetryableError (can be retried)
    - S3ThrottlingError
    - S3TimeoutError
    - BundleCreationError
    - DiskSpaceError
    - MemoryLimitError
    - TransientDynamoError (existing)
    - BundlingTimeoutError (existing)
    - BatchTooLargeError (existing)
  - NonRetryableError (should not be retried)
    - ValidationError
      - InvalidS3EventError
      - InvalidConfigurationError
    - S3AccessDeniedError
    - S3ObjectNotFoundError
    - ConfigurationError
"""

from typing import Any, Dict, Optional


class DataAggregatorError(Exception):
    """Base exception for all Data Aggregator service errors."""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = dict(context) if context else {}  # Copy context to prevent mutation
        self.correlation_id = correlation_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for structured logging."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context,
            "correlation_id": self.correlation_id,
            "retryable": isinstance(self, RetryableError)
        }


class RetryableError(DataAggregatorError):
    """Base class for errors that can be retried."""
    pass


class NonRetryableError(DataAggregatorError):
    """Base class for errors that should not be retried."""
    pass


# === S3-Related Errors ===

class S3Error(DataAggregatorError):
    """Base class for S3-related errors."""
    pass


class S3ObjectNotFoundError(S3Error, NonRetryableError):
    """Raised when a requested S3 object does not exist."""
    
    def __init__(self, bucket: str, key: str, **kwargs):
        message = f"S3 object not found: s3://{bucket}/{key}"
        context = {"bucket": bucket, "key": key}
        super().__init__(message, error_code="S3_OBJECT_NOT_FOUND", context=context, **kwargs)


class S3AccessDeniedError(S3Error, NonRetryableError):
    """Raised when access is denied to an S3 object."""
    
    def __init__(self, bucket: str, key: str, **kwargs):
        message = f"Access denied to S3 object: s3://{bucket}/{key}"
        context = {"bucket": bucket, "key": key}
        super().__init__(message, error_code="S3_ACCESS_DENIED", context=context, **kwargs)


class S3ThrottlingError(S3Error, RetryableError):
    """Raised when S3 operations are being throttled."""
    
    def __init__(self, operation: str, **kwargs):
        message = f"S3 operation throttled: {operation}"
        context = {"operation": operation}
        super().__init__(message, error_code="S3_THROTTLING", context=context, **kwargs)


class S3TimeoutError(S3Error, RetryableError):
    """Raised when S3 operations timeout."""
    
    def __init__(self, operation: str, timeout_seconds: float, **kwargs):
        message = f"S3 operation timed out after {timeout_seconds}s: {operation}"
        # Start with provided context, then add our default context
        context = {}
        if 'context' in kwargs:
            context.update(kwargs.pop('context'))
        # Add our default context (this will override any conflicting keys)
        context.update({"operation": operation, "timeout_seconds": timeout_seconds})
        super().__init__(message, error_code="S3_TIMEOUT", context=context, **kwargs)


# === Validation Errors ===

class ValidationError(NonRetryableError):
    """Base class for validation errors."""
    pass


class InvalidS3EventError(ValidationError):
    """Raised when S3 event structure is invalid."""
    
    def __init__(self, message: str, **kwargs):
        # Don't override error_code if it's already provided in kwargs
        if 'error_code' not in kwargs:
            kwargs['error_code'] = "INVALID_S3_EVENT"
        super().__init__(message, **kwargs)


class InvalidConfigurationError(ValidationError):
    """Raised when configuration is invalid."""
    
    def __init__(self, config_field: str, value: Any = None, **kwargs):
        message = f"Invalid configuration: {config_field}"
        context = {"config_field": config_field, "value": str(value) if value is not None else None}
        super().__init__(message, error_code="INVALID_CONFIGURATION", context=context, **kwargs)


# === Processing Errors ===

class ProcessingError(DataAggregatorError):
    """Base class for processing errors."""
    pass


class BundleCreationError(ProcessingError, RetryableError):
    """Raised when bundle creation fails."""
    
    def __init__(self, reason: str, **kwargs):
        message = f"Bundle creation failed: {reason}"
        context = {"reason": reason}
        super().__init__(message, error_code="BUNDLE_CREATION_FAILED", context=context, **kwargs)


class DiskSpaceError(ProcessingError, RetryableError):
    """Raised when disk space is insufficient."""
    
    def __init__(self, required_bytes: int, available_bytes: int, **kwargs):
        message = f"Insufficient disk space: required {required_bytes}, available {available_bytes}"
        context = {"required_bytes": required_bytes, "available_bytes": available_bytes}
        super().__init__(message, error_code="INSUFFICIENT_DISK_SPACE", context=context, **kwargs)


class MemoryLimitError(ProcessingError, RetryableError):
    """Raised when memory limit is exceeded."""
    
    def __init__(self, operation: str, **kwargs):
        message = f"Memory limit exceeded during: {operation}"
        context = {"operation": operation}
        super().__init__(message, error_code="MEMORY_LIMIT_EXCEEDED", context=context, **kwargs)


# === Configuration Errors ===

class ConfigurationError(NonRetryableError):
    """Raised when there's an error in the application configuration."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, error_code="CONFIGURATION_ERROR", **kwargs)


# === Legacy Exceptions (preserved for backward compatibility) ===

class SQSBatchProcessingError(RetryableError):
    """Base class for errors that require the entire batch to be retried by SQS."""
    pass


class BundlingTimeoutError(SQSBatchProcessingError):
    """Raised when not enough Lambda time is left to safely create a bundle."""
    
    def __init__(self, remaining_time_ms: int, **kwargs):
        message = f"Insufficient time remaining for bundling: {remaining_time_ms}ms"
        context = {"remaining_time_ms": remaining_time_ms}
        super().__init__(message, error_code="BUNDLING_TIMEOUT", context=context, **kwargs)


class BatchTooLargeError(SQSBatchProcessingError):
    """Raised when the sum of input object sizes exceeds the configured limit."""
    
    def __init__(self, batch_size_bytes: int, limit_bytes: int, **kwargs):
        message = f"Batch size {batch_size_bytes} exceeds limit {limit_bytes}"
        context = {"batch_size_bytes": batch_size_bytes, "limit_bytes": limit_bytes}
        super().__init__(message, error_code="BATCH_TOO_LARGE", context=context, **kwargs)


class TransientDynamoError(SQSBatchProcessingError):
    """Raised for transient DynamoDB issues during the idempotency check."""
    
    def __init__(self, operation: str, **kwargs):
        message = f"Transient DynamoDB error during: {operation}"
        context = {"operation": operation}
        super().__init__(message, error_code="TRANSIENT_DYNAMO_ERROR", context=context, **kwargs)


# Backward compatibility alias
class ObjectNotFoundError(S3ObjectNotFoundError):
    """Legacy alias for S3ObjectNotFoundError."""
    
    def __init__(self, message: str = None, bucket: str = None, key: str = None, **kwargs):
        if bucket and key:
            super().__init__(bucket, key, **kwargs)
        else:
            # Fallback for legacy usage
            super().__init__("unknown", "unknown", **kwargs)
            self.message = message or "S3 object not found"


# === Utility Functions ===

def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable."""
    return isinstance(error, RetryableError)


def get_error_context(error: Exception) -> Dict[str, Any]:
    """Extract error context for logging."""
    if isinstance(error, DataAggregatorError):
        return error.to_dict()
    else:
        return {
            "error_type": error.__class__.__name__,
            "message": str(error),
            "retryable": False  # Unknown errors default to non-retryable
        }

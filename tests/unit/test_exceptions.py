# tests/unit/test_exceptions.py

import pytest
import json
from unittest.mock import Mock
from data_aggregator.exceptions import (
    DataAggregatorError,
    RetryableError,
    NonRetryableError,
    S3Error,
    S3ObjectNotFoundError,
    S3AccessDeniedError,
    S3ThrottlingError,
    S3TimeoutError,
    ValidationError,
    InvalidS3EventError,
    InvalidConfigurationError,
    ProcessingError,
    BundleCreationError,
    DiskSpaceError,
    MemoryLimitError,
    ConfigurationError,
    SQSBatchProcessingError,
    BundlingTimeoutError,
    BatchTooLargeError,
    TransientDynamoError,
    ObjectNotFoundError,
    is_retryable_error,
    get_error_context
)


class TestDataAggregatorError:
    """Test the base DataAggregatorError class."""
    
    def test_basic_initialization(self):
        """Test basic error initialization."""
        error = DataAggregatorError("Test message")
        assert str(error) == "Test message"
        assert error.message == "Test message"
        assert error.error_code == "DataAggregatorError"
        assert error.context == {}
        assert error.correlation_id is None
    
    def test_full_initialization(self):
        """Test error initialization with all parameters."""
        context = {"key": "value"}
        error = DataAggregatorError(
            "Test message",
            error_code="CUSTOM_CODE",
            context=context,
            correlation_id="test-123"
        )
        assert error.message == "Test message"
        assert error.error_code == "CUSTOM_CODE"
        assert error.context == context
        assert error.correlation_id == "test-123"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        error = DataAggregatorError(
            "Test message",
            error_code="TEST_CODE",
            context={"key": "value"},
            correlation_id="test-123"
        )
        result = error.to_dict()
        expected = {
            "error_type": "DataAggregatorError",
            "error_code": "TEST_CODE",
            "message": "Test message",
            "context": {"key": "value"},
            "correlation_id": "test-123",
            "retryable": False
        }
        assert result == expected


class TestS3Errors:
    """Test S3-related error classes."""
    
    def test_s3_object_not_found_error(self):
        """Test S3ObjectNotFoundError initialization."""
        error = S3ObjectNotFoundError("test-bucket", "test-key")
        assert "s3://test-bucket/test-key" in str(error)
        assert error.error_code == "S3_OBJECT_NOT_FOUND"
        assert error.context["bucket"] == "test-bucket"
        assert error.context["key"] == "test-key"
        assert isinstance(error, NonRetryableError)
        assert isinstance(error, S3Error)
    
    def test_s3_access_denied_error(self):
        """Test S3AccessDeniedError initialization."""
        error = S3AccessDeniedError("test-bucket", "test-key")
        assert "Access denied" in str(error)
        assert error.error_code == "S3_ACCESS_DENIED"
        assert error.context["bucket"] == "test-bucket"
        assert error.context["key"] == "test-key"
        assert isinstance(error, NonRetryableError)
        assert isinstance(error, S3Error)
    
    def test_s3_throttling_error(self):
        """Test S3ThrottlingError initialization."""
        error = S3ThrottlingError("GetObject")
        assert "throttled" in str(error)
        assert error.error_code == "S3_THROTTLING"
        assert error.context["operation"] == "GetObject"
        assert isinstance(error, RetryableError)
        assert isinstance(error, S3Error)
    
    def test_s3_timeout_error(self):
        """Test S3TimeoutError initialization."""
        error = S3TimeoutError("GetObject", 30.0)
        assert "timed out" in str(error)
        assert "30.0s" in str(error)
        assert error.error_code == "S3_TIMEOUT"
        assert error.context["operation"] == "GetObject"
        assert error.context["timeout_seconds"] == 30.0
        assert isinstance(error, RetryableError)
        assert isinstance(error, S3Error)


class TestValidationErrors:
    """Test validation error classes."""
    
    def test_validation_error(self):
        """Test ValidationError base class."""
        error = ValidationError("Invalid input")
        assert str(error) == "Invalid input"
        assert isinstance(error, NonRetryableError)
    
    def test_invalid_s3_event_error(self):
        """Test InvalidS3EventError initialization."""
        error = InvalidS3EventError("Missing required field")
        assert str(error) == "Missing required field"
        assert error.error_code == "INVALID_S3_EVENT"
        assert isinstance(error, ValidationError)
        assert isinstance(error, NonRetryableError)
    
    def test_invalid_configuration_error(self):
        """Test InvalidConfigurationError initialization."""
        error = InvalidConfigurationError("max_bundle_size", "invalid_value")
        assert "Invalid configuration" in str(error)
        assert error.error_code == "INVALID_CONFIGURATION"
        assert error.context["config_field"] == "max_bundle_size"
        assert error.context["value"] == "invalid_value"
        assert isinstance(error, ValidationError)
        assert isinstance(error, NonRetryableError)


class TestProcessingErrors:
    """Test processing error classes."""
    
    def test_bundle_creation_error(self):
        """Test BundleCreationError initialization."""
        error = BundleCreationError("Compression failed")
        assert "Bundle creation failed" in str(error)
        assert error.error_code == "BUNDLE_CREATION_FAILED"
        assert error.context["reason"] == "Compression failed"
        assert isinstance(error, RetryableError)
        assert isinstance(error, ProcessingError)
    
    def test_disk_space_error(self):
        """Test DiskSpaceError initialization."""
        error = DiskSpaceError(1000000, 500000)
        assert "Insufficient disk space" in str(error)
        assert error.error_code == "INSUFFICIENT_DISK_SPACE"
        assert error.context["required_bytes"] == 1000000
        assert error.context["available_bytes"] == 500000
        assert isinstance(error, RetryableError)
        assert isinstance(error, ProcessingError)
    
    def test_memory_limit_error(self):
        """Test MemoryLimitError initialization."""
        error = MemoryLimitError("file_processing")
        assert "Memory limit exceeded" in str(error)
        assert error.error_code == "MEMORY_LIMIT_EXCEEDED"
        assert error.context["operation"] == "file_processing"
        assert isinstance(error, RetryableError)
        assert isinstance(error, ProcessingError)


class TestConfigurationError:
    """Test ConfigurationError class."""
    
    def test_configuration_error(self):
        """Test ConfigurationError initialization."""
        error = ConfigurationError("Invalid environment variable")
        assert str(error) == "Invalid environment variable"
        assert error.error_code == "CONFIGURATION_ERROR"
        assert isinstance(error, NonRetryableError)


class TestLegacyErrors:
    """Test legacy error classes for backward compatibility."""
    
    def test_bundling_timeout_error(self):
        """Test BundlingTimeoutError initialization."""
        error = BundlingTimeoutError(5000)
        assert "Insufficient time remaining" in str(error)
        assert error.error_code == "BUNDLING_TIMEOUT"
        assert error.context["remaining_time_ms"] == 5000
        assert isinstance(error, RetryableError)
        assert isinstance(error, SQSBatchProcessingError)
    
    def test_batch_too_large_error(self):
        """Test BatchTooLargeError initialization."""
        error = BatchTooLargeError(2000000, 1000000)
        assert "exceeds limit" in str(error)
        assert error.error_code == "BATCH_TOO_LARGE"
        assert error.context["batch_size_bytes"] == 2000000
        assert error.context["limit_bytes"] == 1000000
        assert isinstance(error, RetryableError)
        assert isinstance(error, SQSBatchProcessingError)
    
    def test_transient_dynamo_error(self):
        """Test TransientDynamoError initialization."""
        error = TransientDynamoError("put_item")
        assert "Transient DynamoDB error" in str(error)
        assert error.error_code == "TRANSIENT_DYNAMO_ERROR"
        assert error.context["operation"] == "put_item"
        assert isinstance(error, RetryableError)
        assert isinstance(error, SQSBatchProcessingError)
    
    def test_object_not_found_error_with_bucket_key(self):
        """Test ObjectNotFoundError backward compatibility with bucket and key."""
        error = ObjectNotFoundError(bucket="test-bucket", key="test-key")
        assert isinstance(error, S3ObjectNotFoundError)
        assert error.context["bucket"] == "test-bucket"
        assert error.context["key"] == "test-key"
    
    def test_object_not_found_error_legacy_message(self):
        """Test ObjectNotFoundError backward compatibility with message only."""
        error = ObjectNotFoundError(message="Custom message")
        assert error.message == "Custom message"
        assert isinstance(error, S3ObjectNotFoundError)


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_is_retryable_error_with_retryable_errors(self):
        """Test is_retryable_error function with retryable errors."""
        retryable_errors = [
            S3ThrottlingError("test"),
            S3TimeoutError("test", 30.0),
            BundleCreationError("test"),
            MemoryLimitError("test"),
            DiskSpaceError(1000, 500),
            BundlingTimeoutError(5000),
            BatchTooLargeError(2000, 1000),
            TransientDynamoError("test")
        ]
        
        for error in retryable_errors:
            assert is_retryable_error(error) is True
    
    def test_is_retryable_error_with_non_retryable_errors(self):
        """Test is_retryable_error function with non-retryable errors."""
        non_retryable_errors = [
            S3ObjectNotFoundError("bucket", "key"),
            S3AccessDeniedError("bucket", "key"),
            ValidationError("test"),
            InvalidS3EventError("test"),
            InvalidConfigurationError("field", "value"),
            ConfigurationError("test")
        ]
        
        for error in non_retryable_errors:
            assert is_retryable_error(error) is False
    
    def test_is_retryable_error_with_standard_exceptions(self):
        """Test is_retryable_error function with standard Python exceptions."""
        standard_errors = [
            ValueError("test"),
            RuntimeError("test"),
            Exception("test")
        ]
        
        for error in standard_errors:
            assert is_retryable_error(error) is False
    
    def test_get_error_context_with_data_aggregator_error(self):
        """Test get_error_context with DataAggregatorError."""
        error = S3TimeoutError("GetObject", 30.0, correlation_id="test-123")
        context = get_error_context(error)
        
        assert context["error_type"] == "S3TimeoutError"
        assert context["error_code"] == "S3_TIMEOUT"
        assert context["retryable"] is True
        assert context["correlation_id"] == "test-123"
        assert "GetObject" in context["message"]
    
    def test_get_error_context_with_standard_error(self):
        """Test get_error_context with standard Python error."""
        error = ValueError("Invalid value")
        context = get_error_context(error)
        
        assert context["error_type"] == "ValueError"
        assert context["message"] == "Invalid value"
        assert context["retryable"] is False


class TestErrorInheritance:
    """Test error inheritance hierarchy."""
    
    def test_s3_error_inheritance(self):
        """Test that S3 errors inherit from correct base classes."""
        s3_error = S3ObjectNotFoundError("bucket", "key")
        assert isinstance(s3_error, S3Error)
        assert isinstance(s3_error, NonRetryableError)
        assert isinstance(s3_error, DataAggregatorError)
        
        s3_retryable = S3ThrottlingError("test")
        assert isinstance(s3_retryable, S3Error)
        assert isinstance(s3_retryable, RetryableError)
        assert isinstance(s3_retryable, DataAggregatorError)
    
    def test_validation_error_inheritance(self):
        """Test that validation errors inherit from correct base classes."""
        validation_error = InvalidS3EventError("test")
        assert isinstance(validation_error, ValidationError)
        assert isinstance(validation_error, NonRetryableError)
        assert isinstance(validation_error, DataAggregatorError)
    
    def test_processing_error_inheritance(self):
        """Test that processing errors inherit from correct base classes."""
        processing_error = BundleCreationError("test")
        assert isinstance(processing_error, ProcessingError)
        assert isinstance(processing_error, RetryableError)
        assert isinstance(processing_error, DataAggregatorError)
    
    def test_legacy_error_inheritance(self):
        """Test that legacy errors inherit from correct base classes."""
        legacy_error = BundlingTimeoutError(5000)
        assert isinstance(legacy_error, SQSBatchProcessingError)
        assert isinstance(legacy_error, RetryableError)
        assert isinstance(legacy_error, DataAggregatorError)


class TestErrorChaining:
    """Test error chaining and cause tracking."""
    
    def test_error_chaining_with_cause(self):
        """Test that errors can be chained with proper cause tracking."""
        original_error = ValueError("Original error")
        try:
            raise original_error
        except ValueError as e:
            chained_error = S3ObjectNotFoundError("bucket", "key")
            chained_error.__cause__ = e
            
            assert chained_error.__cause__ is original_error
    
    def test_error_context_preservation(self):
        """Test that error context is preserved during chaining."""
        original_context = {"operation": "download", "attempt": 1}
        error = S3TimeoutError("GetObject", 30.0, context=original_context)
        
        # Simulate chaining
        chained_error = BundleCreationError("Failed due to timeout")
        chained_error.__cause__ = error
        
        # S3TimeoutError merges provided context with its own default context
        expected_context = {
            "operation": "GetObject",  # S3TimeoutError overrides this
            "timeout_seconds": 30.0,   # S3TimeoutError adds this
            "attempt": 1               # From original context
        }
        assert error.context == expected_context
        assert chained_error.__cause__.context == expected_context


class TestErrorSerialization:
    """Test error serialization and deserialization."""
    
    def test_to_dict_serialization(self):
        """Test that to_dict produces serializable output."""
        error = S3TimeoutError(
            "GetObject", 
            30.0, 
            context={"additional": "data"},
            correlation_id="test-123"
        )
        
        result = error.to_dict()
        
        # Ensure all values are JSON serializable
        json_str = json.dumps(result)
        assert json_str is not None
        
        # Verify structure
        assert "error_type" in result
        assert "error_code" in result
        assert "message" in result
        assert "context" in result
        assert "correlation_id" in result
        assert "retryable" in result
    
    def test_context_serialization(self):
        """Test that error context is JSON serializable."""
        context = {
            "string": "test",
            "number": 42,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"}
        }
        
        error = ValidationError("Test", context=context)
        
        # Should be able to serialize the context
        serialized = json.dumps(error.context)
        deserialized = json.loads(serialized)
        
        assert deserialized == context
    
    def test_get_error_context_serialization(self):
        """Test that get_error_context returns serializable data."""
        error = S3TimeoutError(
            "Timeout occurred",
            30.0,
            correlation_id="req-456",
            context={"bucket": "test", "timeout_seconds": 30}
        )
        
        error_context = get_error_context(error)
        
        # Should be able to serialize the entire error context
        serialized = json.dumps(error_context)
        deserialized = json.loads(serialized)
        
        assert deserialized == error_context


class TestErrorContextHandling:
    """Test error context handling and manipulation."""
    
    def test_context_immutability(self):
        """Test that error context cannot be accidentally modified."""
        original_context = {"key": "value"}
        error = ValidationError("Test", context=original_context)
        
        # Modify original context
        original_context["new_key"] = "new_value"
        
        # Error context should not be affected
        assert "new_key" not in error.context
        assert error.context == {"key": "value"}
    
    def test_context_with_additional_kwargs(self):
        """Test error creation with additional context via kwargs."""
        error = S3ObjectNotFoundError(
            "test-bucket", 
            "test-key",
            correlation_id="test-123"
        )
        
        assert error.correlation_id == "test-123"
        assert error.context["bucket"] == "test-bucket"
        assert error.context["key"] == "test-key"
    
    def test_error_code_defaults(self):
        """Test that error codes default correctly."""
        # Test with explicit error code
        error1 = InvalidS3EventError("test", error_code="CUSTOM_CODE")
        assert error1.error_code == "CUSTOM_CODE"
        
        # Test with default error code
        error2 = InvalidS3EventError("test")
        assert error2.error_code == "INVALID_S3_EVENT"

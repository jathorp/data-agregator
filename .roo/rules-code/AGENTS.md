# Project Coding Conventions

## Code Modularity for Reuse

Components are designed for future sharing across multiple Lambda functions:

```python
# Reusable components in src/data_aggregator/
from data_aggregator.schemas import S3EventRecord, S3EventNotificationRecord  # Shared schema definitions
from data_aggregator.exceptions import S3TimeoutError, DataAggregatorError  # Common exception types
from data_aggregator.config import AppConfig, get_config  # Environment configuration pattern
from data_aggregator.clients import S3Client  # Reusable S3 operations
from data_aggregator.security import sanitize_s3_key  # Security utilities

# Design patterns for cross-Lambda sharing
class ReusableProcessor:
    """Base class designed for inheritance across Lambda functions"""
    def __init__(self, config: AppConfig):
        self.config = config
    
    def process_with_timeout_guard(self, context) -> bool:
        """Shared timeout management logic"""
        return context.get_remaining_time_in_millis() > self.config.timeout_guard_threshold_ms
```

## Cost-Efficient Patterns

All code patterns prioritize AWS cost optimization:

```python
# Memory-efficient processing with SpooledTemporaryFile
from tempfile import SpooledTemporaryFile
from typing import cast, BinaryIO

# Stays in memory until threshold, then spills to disk
output_spool = cast(BinaryIO, SpooledTemporaryFile(max_size=config.spool_file_max_size_bytes, mode="w+b"))

# ARM64 Graviton2 optimization - ensure dependencies support ARM64
# Use native Python libraries where possible to avoid compatibility issues

# Batch processing to minimize Lambda invocations
def process_batch_efficiently(records: list[S3EventNotificationRecord]) -> dict:
    """Process multiple records in single invocation to reduce costs"""
    # Implementation prioritizes throughput over individual record latency
```

## Schema Architecture

```python
# Use TypedDict for static analysis, Pydantic for runtime validation
from .schemas import S3EventRecord, S3EventNotificationRecord

# Static typing (IDE/mypy support) - TypedDict for function signatures
def process_static(record: S3EventRecord) -> None: ...

# Runtime validation with automatic sanitization - Pydantic for actual processing
parsed = S3EventNotificationRecord.model_validate(raw_s3_record)
safe_key = parsed.s3.object.key  # Automatically sanitized for security
original_key = parsed.s3.object.original_key  # Preserved for S3 operations
bucket_name = parsed.s3.bucket.name  # Validated bucket name
file_size = parsed.s3.object.size  # Validated file size
```

## Memory Management Patterns

```python
# Use SpooledTemporaryFile for Lambda memory efficiency
from tempfile import SpooledTemporaryFile
from typing import cast, BinaryIO

output_spool = cast(BinaryIO, SpooledTemporaryFile(max_size=config.spool_file_max_size_bytes, mode="w+b"))

# Implement timeout-aware processing
if context.get_remaining_time_in_millis() < config.timeout_guard_threshold_ms:
    logger.warning("Timeout threshold reached. Finalizing bundle.")
    break  # Stop processing new files when approaching timeout
```

## Exception Handling

```python
# Use structured exceptions with context
raise S3TimeoutError(
    operation="GetObject",
    timeout_seconds=30.0,
    context={"bucket": "landing-bucket", "key": "file.txt"}
)

# Extract safe context for logging
error_context = exception.to_dict()  # Excludes sensitive data
```

## Idempotency Implementation

```python
# Generate collision-proof keys using S3 metadata
def _make_idempotency_key(key: str, version: str | None, sequencer: str) -> str:
    unique_part = version or sequencer
    raw = json.dumps({"k": key, "u": unique_part}, separators=(",", ":"))
    return quote(raw, safe="")
```

## SQS Integration

```python
# Return proper format for partial batch failures
return {"batchItemFailures": [{"itemIdentifier": message_id}]}
# This enables SQS to retry only failed messages, not the entire batch
# Project Debugging Guide

## Test Execution Requirements

```bash
# E2E tests must be run from e2e_tests/ directory
cd e2e_tests && python main.py --config configs/config_00_singe_file.json
# Running from project root will fail
```

## Direct Lambda Testing

```python
# Use special payload flag to bypass SQS for testing
payload = {
    "e2e_test_direct_invoke": True,
    "records": [s3_event_records]  # Direct S3 event format
}
# Only works in dev/test environments - blocked in production
```

## Test Environment Isolation

```python
# Different S3 prefixes prevent SQS listener conflicts
if test_type in ["direct_invoke", "memory_pressure"]:
    base_prefix = "direct-invoke-tests"  # SQS ignores this prefix
else:
    base_prefix = "data"  # SQS listens to this prefix
```

## Lambda Log Analysis

```bash
# Look for specific log messages that indicate system behavior
grep "Predicted disk usage exceeds limit" lambda_logs.txt
grep "Timeout threshold reached" lambda_logs.txt
grep "processed_records" lambda_logs.txt  # Shows partial processing count
```

## Memory and Resource Debugging

```python
# Lambda memory errors have specific signatures
if "MemoryLimitError" in log_result or "Runtime.OutOfMemory" in log_result:
    # Memory pressure detected - check SpooledTemporaryFile usage
```

## SQS Batch Processing Debugging

```python
# Correct format for partial batch failures
return {"batchItemFailures": [{"itemIdentifier": message_id}]}
# Wrong format causes infinite retry loops or lost messages
```

## Common Troubleshooting

- **E2E Test Failures**: Ensure running from `e2e_tests/` directory
- **Lambda Timeouts**: Check timeout-aware processing logic in core.py
- **Memory Issues**: Verify SpooledTemporaryFile configuration
- **SQS Retries**: Validate partial batch failure return format
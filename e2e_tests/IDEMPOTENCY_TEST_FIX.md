# Idempotency Test Fix Summary

## Problem Description

The e2e test 07 (idempotency test) was experiencing intermittent failures. The test is designed to validate versionId-based idempotency by:

1. Uploading a file to S3
2. Waiting for it to be processed into a bundle
3. Uploading a new version to the same S3 key
4. Verifying that a second, distinct bundle is created

The test was failing intermittently with the error message indicating that it sometimes passed and sometimes failed when run multiple times in succession.

## Root Cause Analysis

The investigation revealed two main issues:

### 1. KeyError Bug
The `_run_idempotency_test()` method contained a line that tried to remove a bundle key from `processed_bundle_keys` that was never added there:

```python
self.processed_bundle_keys.remove(bundle_key_1)  # This caused KeyError
```

The `_wait_for_bundle_and_get_key()` method only returns bundle keys but doesn't modify the `processed_bundle_keys` set.

### 2. Test Environment Contamination
The more critical issue was that the existing `_cleanup_stale_bundles()` method only removed bundles older than 240 seconds. When tests were run within 4 minutes of each other, bundles from previous test runs would remain in the distribution bucket, causing validation failures when the current test found "extra" files that weren't part of its expected manifest.

## Solution Implemented

### 1. Fixed KeyError
Removed the problematic line:
```python
# REMOVED: self.processed_bundle_keys.remove(bundle_key_1)
```

### 2. Added Complete Bundle Cleanup
Added a new method `_cleanup_all_bundles()` that removes ALL bundles from the distribution bucket regardless of age:

```python
def _cleanup_all_bundles(self):
    """Deletes ALL bundles from the distribution bucket to ensure a completely clean state."""
    self.console.print("\n--- [bold yellow]Complete Bundle Cleanup[/bold yellow] ---")
    try:
        paginator = self.s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.config.distribution_bucket)
        
        all_bundles = []
        for page in pages:
            for obj in page.get("Contents", []):
                if "bundle-" in obj["Key"]:
                    all_bundles.append({"Key": obj["Key"]})
        
        if not all_bundles:
            self.console.log("No bundles found in distribution bucket. Environment is clean.")
            return
        
        self.console.log(f"Found {len(all_bundles)} bundle(s) to delete...")
        # S3 delete_objects has a limit of 1000 keys per request
        for i in range(0, len(all_bundles), 1000):
            chunk = all_bundles[i : i + 1000]
            self.s3.delete_objects(
                Bucket=self.config.distribution_bucket, Delete={"Objects": chunk}
            )
        self.console.log("[green]✓ All bundles cleaned up successfully.[/green]")
        
    except Exception as e:
        self.console.log(f"[bold red]Could not perform complete cleanup: {e}[/bold red]")
```

### 3. Modified Idempotency Test
Updated `_run_idempotency_test()` to call the complete cleanup at the beginning:

```python
def _run_idempotency_test(self) -> int:
    """
    Tests the versioning behavior by uploading a file, then overwriting it.
    It verifies that BOTH versions are processed, as each is a unique object.
    This validates the core business logic for handling updated data.
    """
    self.console.print(
        "\n--- [bold blue]File Versioning Test (Scenario B)[/bold blue] ---"
    )

    # Ensure completely clean environment for idempotency test
    # This prevents interference from previous test runs
    self._cleanup_all_bundles()
    
    # ... rest of the test logic
```

## Validation

Created a test script `test_idempotency_fix.py` that validates:

1. ✓ `_cleanup_all_bundles()` method exists with correct signature
2. ✓ `_run_idempotency_test()` calls `_cleanup_all_bundles()` at the beginning
3. ✓ `_cleanup_all_bundles()` contains correct cleanup logic
4. ✓ Original KeyError bug has been fixed (problematic line removed)

## Expected Outcome

With this fix, the idempotency test should now:

1. Start with a completely clean distribution bucket every time
2. Not experience KeyError exceptions
3. Pass consistently without intermittent failures
4. Properly validate that the system creates distinct bundles for each file version

## Files Modified

- `data-agregator/e2e_tests/components/runner.py`: Added `_cleanup_all_bundles()` method and modified `_run_idempotency_test()`
- `data-agregator/e2e_tests/test_idempotency_fix.py`: Created validation test script
- `data-agregator/e2e_tests/IDEMPOTENCY_TEST_FIX.md`: This documentation

## Testing

To test the fix without AWS credentials:
```bash
cd data-agregator/e2e_tests
uv run python test_idempotency_fix.py
```

To run the actual idempotency test (requires AWS credentials):
```bash
cd data-agregator/e2e_tests
uv run python main.py -c configs/config_07_idempotency.json

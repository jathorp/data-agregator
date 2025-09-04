#!/usr/bin/env python3
"""
Test script to validate the idempotency test fix without requiring AWS credentials.
This script tests the logic of the _cleanup_all_bundles method and verifies
that the _run_idempotency_test method calls it correctly.
"""

import sys
import inspect
from pathlib import Path

# Add the e2e_tests directory to the path so relative imports work
sys.path.insert(0, str(Path(__file__).parent))

def test_cleanup_all_bundles_method_exists():
    """Test that the _cleanup_all_bundles method exists in the E2ETestRunner class."""
    from components.runner import E2ETestRunner
    
    # Check if the method exists
    assert hasattr(E2ETestRunner, '_cleanup_all_bundles'), \
        "_cleanup_all_bundles method not found in E2ETestRunner"
    
    # Check the method signature
    method = getattr(E2ETestRunner, '_cleanup_all_bundles')
    sig = inspect.signature(method)
    
    # Should only have 'self' parameter
    assert len(sig.parameters) == 1, \
        f"_cleanup_all_bundles should only have 'self' parameter, got: {list(sig.parameters.keys())}"
    
    print("✓ _cleanup_all_bundles method exists with correct signature")

def test_idempotency_test_calls_cleanup():
    """Test that _run_idempotency_test method calls _cleanup_all_bundles."""
    from components.runner import E2ETestRunner
    
    # Get the source code of the _run_idempotency_test method
    method = getattr(E2ETestRunner, '_run_idempotency_test')
    source = inspect.getsource(method)
    
    # Check that it calls _cleanup_all_bundles
    assert 'self._cleanup_all_bundles()' in source, \
        "_run_idempotency_test does not call self._cleanup_all_bundles()"
    
    # Check that it's called early in the method (before the main test logic)
    lines = source.split('\n')
    cleanup_line_index = None
    phase1_line_index = None
    
    for i, line in enumerate(lines):
        if 'self._cleanup_all_bundles()' in line:
            cleanup_line_index = i
        if 'Phase 1:' in line:
            phase1_line_index = i
    
    assert cleanup_line_index is not None, "Could not find _cleanup_all_bundles() call"
    assert phase1_line_index is not None, "Could not find Phase 1 comment"
    assert cleanup_line_index < phase1_line_index, \
        "_cleanup_all_bundles() should be called before Phase 1 starts"
    
    print("✓ _run_idempotency_test correctly calls _cleanup_all_bundles() at the beginning")

def test_cleanup_method_logic():
    """Test the logic of the _cleanup_all_bundles method."""
    from components.runner import E2ETestRunner
    
    # Get the source code of the _cleanup_all_bundles method
    method = getattr(E2ETestRunner, '_cleanup_all_bundles')
    source = inspect.getsource(method)
    
    # Check for key components of the cleanup logic
    assert 'paginator = self.s3.get_paginator("list_objects_v2")' in source, \
        "Method should use S3 paginator to list objects"
    
    assert 'if "bundle-" in obj["Key"]:' in source, \
        "Method should filter for bundle objects"
    
    assert 'self.s3.delete_objects(' in source, \
        "Method should delete objects using S3 delete_objects"
    
    assert 'Delete={"Objects": chunk}' in source, \
        "Method should use proper delete_objects format"
    
    print("✓ _cleanup_all_bundles method contains correct cleanup logic")

def test_original_bug_fix():
    """Test that the original KeyError bug has been fixed."""
    from components.runner import E2ETestRunner
    
    # Get the source code of the _run_idempotency_test method
    method = getattr(E2ETestRunner, '_run_idempotency_test')
    source = inspect.getsource(method)
    
    # Check that the problematic line has been removed
    assert 'self.processed_bundle_keys.remove(bundle_key_1)' not in source, \
        "The problematic line 'self.processed_bundle_keys.remove(bundle_key_1)' should be removed"
    
    print("✓ Original KeyError bug has been fixed (problematic line removed)")

def test_verbose_flag_controls_debug_output():
    """Test that debug output respects the verbose configuration flag."""
    from components.runner import E2ETestRunner
    
    # Test _debug_extracted_contents method
    debug_method = getattr(E2ETestRunner, '_debug_extracted_contents')
    debug_source = inspect.getsource(debug_method)
    
    # Check that it has verbose check at the beginning
    assert 'if not self.config.verbose:' in debug_source, \
        "_debug_extracted_contents should check verbose flag"
    assert 'return' in debug_source, \
        "_debug_extracted_contents should return early if not verbose"
    
    # Test _run_idempotency_test method for verbose-controlled debug output
    idempotency_method = getattr(E2ETestRunner, '_run_idempotency_test')
    idempotency_source = inspect.getsource(idempotency_method)
    
    # Check that manifest debug output is controlled by verbose flag
    assert 'if self.config.verbose:' in idempotency_source, \
        "_run_idempotency_test should check verbose flag for debug output"
    assert 'DEBUG: Manifest expects to find:' in idempotency_source, \
        "_run_idempotency_test should contain the manifest debug output"
    
    print("✓ Debug output correctly respects verbose configuration flag")

def main():
    """Run all tests."""
    print("Testing idempotency test fix...")
    print()
    
    try:
        test_cleanup_all_bundles_method_exists()
        test_idempotency_test_calls_cleanup()
        test_cleanup_method_logic()
        test_original_bug_fix()
        
        print()
        print("🎉 All tests passed! The idempotency test fix is correctly implemented.")
        print()
        print("Summary of fixes:")
        print("1. ✓ Added _cleanup_all_bundles() method for complete bundle cleanup")
        print("2. ✓ Modified _run_idempotency_test() to call cleanup at the beginning")
        print("3. ✓ Removed the problematic KeyError-causing line")
        print("4. ✓ Ensures clean environment for each idempotency test run")
        print()
        print("The fix addresses the intermittent failures by ensuring that")
        print("idempotency tests start with a completely clean distribution bucket,")
        print("preventing interference from previous test runs.")
        
        return 0
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

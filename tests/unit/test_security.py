# tests/unit/test_security.py

import pytest

from src.data_aggregator.security import sanitize_s3_key
from src.data_aggregator.exceptions import ValidationError


class TestSanitizeS3Key:
    """Test suite for the sanitize_s3_key security function."""

    @pytest.mark.parametrize(
        "key, expected_safe_key",
        [
            # Basic valid cases
            ("/etc/passwd", "etc/passwd"),
            ("C:\\Windows\\System32.dll", "Windows/System32.dll"),
            ("foo/./bar//baz.txt", "foo/bar/baz.txt"),
            
            # NEW: Legitimate filenames containing ".." (not path traversal)
            # These should pass with our refined implementation
            ("my-backup..old.txt", "my-backup..old.txt"),
            ("data..2024-01-01.csv", "data..2024-01-01.csv"),
            ("config..backup.json", "config..backup.json"),
            ("folder/file..backup.txt", "folder/file..backup.txt"),
            ("archive..v1.2.3.tar.gz", "archive..v1.2.3.tar.gz"),
            ("logs/app..debug.log", "logs/app..debug.log"),
            ("temp..file..name.txt", "temp..file..name.txt"),
            
            # Edge cases with dots that should be allowed
            ("file...txt", "file...txt"),
            ("...hidden", "...hidden"),
            ("file..", "file.."),
            ("..file", "..file"),
            
            # Complex paths with legitimate ".." in filenames
            ("backup/2024/data..old/file.txt", "backup/2024/data..old/file.txt"),
            ("nested/folder/config..backup.json", "nested/folder/config..backup.json"),
        ],
    )
    def test_sanitize_s3_key_valid_keys(self, key, expected_safe_key):
        """Test that valid S3 keys are properly sanitized, including legitimate filenames with '..'."""
        assert sanitize_s3_key(key) == expected_safe_key

    @pytest.mark.parametrize(
        "invalid_key, expected_error_code",
        [
            # Path traversal attacks (these should still be blocked)
            ("foo/../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("folder/../secret.txt", "UNSAFE_S3_KEY_PATH"),
            ("../../../../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("foo/../bar/../baz", "UNSAFE_S3_KEY_PATH"),
            
            # Size and format violations
            ("a" * 1025, "INVALID_S3_KEY_FORMAT"),  # Too long
            
            # Control character violations
            ("file\x00name.txt", "INVALID_S3_KEY_FORMAT"),  # NULL character
            ("file\x1fname.txt", "INVALID_S3_KEY_FORMAT"),  # Unit separator
            ("file\x7fname.txt", "INVALID_S3_KEY_FORMAT"),  # DEL character
            ("file\x01name.txt", "INVALID_S3_KEY_FORMAT"),  # Start of heading
            ("file\x1ename.txt", "INVALID_S3_KEY_FORMAT"),  # Record separator
            
            # Empty and invalid paths
            ("", "UNSAFE_S3_KEY_PATH"),  # Empty string
            (".", "UNSAFE_S3_KEY_PATH"),  # Current directory
            ("/", "UNSAFE_S3_KEY_PATH"),  # Root directory becomes empty
            ("//", "UNSAFE_S3_KEY_PATH"),  # Multiple slashes become empty
            
            # Type violations
            (123, "INVALID_S3_KEY_TYPE"),  # Non-string type
            (None, "INVALID_S3_KEY_TYPE"),  # None type
            ([], "INVALID_S3_KEY_TYPE"),  # List type
        ],
    )
    def test_sanitize_s3_key_invalid_keys(self, invalid_key, expected_error_code):
        """Test that invalid S3 keys raise ValidationError with appropriate error codes."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(invalid_key)
        
        assert exc_info.value.error_code == expected_error_code

    def test_sanitize_s3_key_path_traversal_security(self):
        """
        Comprehensive test to ensure path traversal attacks are blocked
        while legitimate filenames with '..' are allowed.
        """
        # These should be BLOCKED (actual path traversal)
        dangerous_paths = [
            "folder/../etc/passwd",
            "../secret.txt", 
            "foo/../bar",
            "../../etc/shadow",
            "dir1/../dir2/../etc/passwd",
        ]
        
        for dangerous_path in dangerous_paths:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(dangerous_path)
            assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"
        
        # These should be ALLOWED (legitimate filenames)
        safe_paths = [
            "my-backup..old.txt",
            "config..v2.json", 
            "data..2024.csv",
            "folder/file..backup.txt",
            "archive..final.tar.gz",
        ]
        
        for safe_path in safe_paths:
            # Should not raise any exception
            result = sanitize_s3_key(safe_path)
            assert result == safe_path  # Should return unchanged

    def test_sanitize_s3_key_control_characters(self):
        """Test that all control characters are properly blocked."""
        # Test various control characters
        control_chars = [
            "\x00",  # NULL
            "\x01",  # Start of Heading
            "\x07",  # Bell
            "\x08",  # Backspace
            "\x0A",  # Line Feed
            "\x0D",  # Carriage Return
            "\x1B",  # Escape
            "\x1F",  # Unit Separator
            "\x7F",  # DEL
        ]
        
        for char in control_chars:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(f"file{char}name.txt")
            assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"

    def test_sanitize_s3_key_windows_paths(self):
        """Test Windows path normalization."""
        windows_paths = [
            ("C:\\Users\\file.txt", "Users/file.txt"),
            ("D:\\data\\backup..old.txt", "data/backup..old.txt"),
            ("E:\\folder\\subfolder\\file.log", "folder/subfolder/file.log"),
        ]
        
        for windows_path, expected in windows_paths:
            assert sanitize_s3_key(windows_path) == expected

    def test_sanitize_s3_key_utf8_length_limit(self):
        """Test UTF-8 byte length validation."""
        # Create a string that's exactly at the limit (1024 bytes)
        # Using 'a' characters (1 byte each in UTF-8)
        at_limit = "a" * 1024
        assert sanitize_s3_key(at_limit) == at_limit
        
        # Create a string that exceeds the limit
        over_limit = "a" * 1025
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(over_limit)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"
        
        # Test with multi-byte UTF-8 characters
        # '€' is 3 bytes in UTF-8, so 342 characters = 1026 bytes (over limit)
        multi_byte_over = "€" * 342
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(multi_byte_over)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"

    def test_sanitize_s3_key_edge_cases(self):
        """Test various edge cases and corner scenarios."""
        edge_cases = [
            # Multiple consecutive slashes
            ("folder///file.txt", "folder/file.txt"),
            
            # Mixed separators
            ("folder\\subfolder/file.txt", "folder/subfolder/file.txt"),
            
            # Current directory references
            ("./folder/file.txt", "folder/file.txt"),
            ("folder/./file.txt", "folder/file.txt"),
            
            # Leading slashes
            ("/folder/file.txt", "folder/file.txt"),
            ("///folder/file.txt", "folder/file.txt"),
            
            # Trailing slashes (should be preserved as part of normalization)
            ("folder/file.txt/", "folder/file.txt"),
        ]
        
        for input_path, expected in edge_cases:
            assert sanitize_s3_key(input_path) == expected

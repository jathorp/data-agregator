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

    # ========================================================================
    # ADVANCED SECURITY TEST CATEGORIES (QA Recommendations)
    # ========================================================================

    def test_sanitize_s3_key_unicode_invisibles(self):
        """
        Test Category 1: Unicode invisible characters and security threats.
        
        Tests for zero-width characters, right-to-left override, and other
        Unicode characters that could be used for security attacks or
        cause display/processing issues.
        """
        unicode_threats = [
            # Zero-width characters
            ("file\u200Bname.txt", "INVALID_S3_KEY_FORMAT"),  # Zero Width Space
            ("file\u200Cname.txt", "INVALID_S3_KEY_FORMAT"),  # Zero Width Non-Joiner
            ("file\u200Dname.txt", "INVALID_S3_KEY_FORMAT"),  # Zero Width Joiner
            ("file\uFEFFname.txt", "INVALID_S3_KEY_FORMAT"),  # Zero Width No-Break Space (BOM)
            
            # Directional override characters (can cause display confusion)
            ("file\u202Ename.txt", "INVALID_S3_KEY_FORMAT"),  # Right-to-Left Override
            ("file\u202Dname.txt", "INVALID_S3_KEY_FORMAT"),  # Left-to-Right Override
            ("file\u202Cname.txt", "INVALID_S3_KEY_FORMAT"),  # Pop Directional Formatting
            
            # Line/paragraph separators
            ("file\u2028name.txt", "INVALID_S3_KEY_FORMAT"),  # Line Separator
            ("file\u2029name.txt", "INVALID_S3_KEY_FORMAT"),  # Paragraph Separator
            
            # Other problematic Unicode
            ("file\u00A0name.txt", "INVALID_S3_KEY_FORMAT"),  # Non-breaking space
            ("file\u1680name.txt", "INVALID_S3_KEY_FORMAT"),  # Ogham space mark
        ]
        
        for dangerous_key, expected_error in unicode_threats:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(dangerous_key)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_leading_trailing_spaces(self):
        """
        Test Category 2: Leading and trailing whitespace handling.
        
        Tests various whitespace characters that could cause issues
        in file systems or be used to disguise malicious filenames.
        """
        whitespace_cases = [
            # Leading/trailing spaces
            (" filename.txt", "INVALID_S3_KEY_FORMAT"),  # Leading space
            ("filename.txt ", "INVALID_S3_KEY_FORMAT"),  # Trailing space
            (" filename.txt ", "INVALID_S3_KEY_FORMAT"),  # Both
            
            # Leading/trailing tabs
            ("\tfilename.txt", "INVALID_S3_KEY_FORMAT"),  # Leading tab
            ("filename.txt\t", "INVALID_S3_KEY_FORMAT"),  # Trailing tab
            
            # Multiple whitespace
            ("  filename.txt", "INVALID_S3_KEY_FORMAT"),  # Multiple leading spaces
            ("filename.txt  ", "INVALID_S3_KEY_FORMAT"),  # Multiple trailing spaces
            
            # Mixed whitespace
            (" \tfilename.txt\t ", "INVALID_S3_KEY_FORMAT"),  # Mixed leading/trailing
            
            # Folder paths with whitespace
            ("folder/ filename.txt", "INVALID_S3_KEY_FORMAT"),  # Space after slash
            ("folder /filename.txt", "INVALID_S3_KEY_FORMAT"),  # Space before slash
        ]
        
        for whitespace_key, expected_error in whitespace_cases:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(whitespace_key)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_windows_device_names(self):
        """
        Test Category 3: Windows reserved device names.
        
        Tests for Windows reserved device names that could cause issues
        when archives are extracted on Windows systems.
        """
        device_names = [
            # Core device names
            ("CON", "UNSAFE_S3_KEY_PATH"),
            ("PRN", "UNSAFE_S3_KEY_PATH"),
            ("AUX", "UNSAFE_S3_KEY_PATH"),
            ("NUL", "UNSAFE_S3_KEY_PATH"),
            
            # COM ports
            ("COM1", "UNSAFE_S3_KEY_PATH"),
            ("COM2", "UNSAFE_S3_KEY_PATH"),
            ("COM9", "UNSAFE_S3_KEY_PATH"),
            
            # LPT ports
            ("LPT1", "UNSAFE_S3_KEY_PATH"),
            ("LPT2", "UNSAFE_S3_KEY_PATH"),
            ("LPT9", "UNSAFE_S3_KEY_PATH"),
            
            # Case variations
            ("con", "UNSAFE_S3_KEY_PATH"),
            ("Con", "UNSAFE_S3_KEY_PATH"),
            ("prn", "UNSAFE_S3_KEY_PATH"),
            ("aux", "UNSAFE_S3_KEY_PATH"),
            
            # With extensions (still reserved on Windows)
            ("CON.txt", "UNSAFE_S3_KEY_PATH"),
            ("PRN.log", "UNSAFE_S3_KEY_PATH"),
            ("AUX.dat", "UNSAFE_S3_KEY_PATH"),
            ("COM1.cfg", "UNSAFE_S3_KEY_PATH"),
            
            # In folder paths
            ("folder/CON", "UNSAFE_S3_KEY_PATH"),
            ("data/PRN.txt", "UNSAFE_S3_KEY_PATH"),
            ("logs/AUX.log", "UNSAFE_S3_KEY_PATH"),
        ]
        
        for device_name, expected_error in device_names:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(device_name)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_mixed_traversal_attempts(self):
        """
        Test Category 4: Mixed path traversal attempts.
        
        Tests for sophisticated path traversal attacks using mixed
        separators, encodings, and obfuscation techniques.
        """
        mixed_traversal = [
            # Mixed separators in traversal
            ("folder\\..\\..\\etc\\passwd", "UNSAFE_S3_KEY_PATH"),
            ("folder/../..\\etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("folder\\../..\\etc/passwd", "UNSAFE_S3_KEY_PATH"),
            
            # URL encoded traversal attempts
            ("folder%2F..%2F..%2Fetc%2Fpasswd", "UNSAFE_S3_KEY_PATH"),  # If URL decoding happens
            ("folder%5C..%5C..%5Cetc%5Cpasswd", "UNSAFE_S3_KEY_PATH"),  # Encoded backslashes
            
            # Double encoded
            ("folder%252F..%252F..%252Fetc%252Fpasswd", "UNSAFE_S3_KEY_PATH"),
            
            # Unicode normalization attacks (if normalization happens)
            ("folder/\u002E\u002E/\u002E\u002E/etc/passwd", "UNSAFE_S3_KEY_PATH"),  # Unicode dots
            
            # Overlong UTF-8 sequences (if present)
            ("folder/\uFF0E\uFF0E/\uFF0E\uFF0E/etc/passwd", "UNSAFE_S3_KEY_PATH"),  # Fullwidth dots
            
            # Mixed with legitimate ".." in filenames
            ("folder/../config..backup.txt", "UNSAFE_S3_KEY_PATH"),  # Should still block traversal part
        ]
        
        for mixed_attack, expected_error in mixed_traversal:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(mixed_attack)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_unicode_length_edge_cases(self):
        """
        Test Category 5: Unicode length edge cases.
        
        Tests for edge cases around UTF-8 byte length limits,
        including multi-byte characters and normalization effects.
        """
        # Test characters with different UTF-8 byte lengths
        
        # 2-byte UTF-8 characters (like é, ñ, etc.)
        two_byte_char = "é"  # 2 bytes in UTF-8
        two_byte_at_limit = two_byte_char * 512  # 512 * 2 = 1024 bytes (at limit)
        two_byte_over_limit = two_byte_char * 513  # 513 * 2 = 1026 bytes (over limit)
        
        # Should pass at limit
        assert sanitize_s3_key(two_byte_at_limit) == two_byte_at_limit
        
        # Should fail over limit
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(two_byte_over_limit)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"
        
        # 3-byte UTF-8 characters (like €, 中, etc.)
        three_byte_char = "€"  # 3 bytes in UTF-8
        three_byte_at_limit = three_byte_char * 341 + "a"  # 341*3 + 1 = 1024 bytes
        three_byte_over_limit = three_byte_char * 342  # 342 * 3 = 1026 bytes
        
        # Should pass at limit
        assert sanitize_s3_key(three_byte_at_limit) == three_byte_at_limit
        
        # Should fail over limit
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(three_byte_over_limit)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"
        
        # 4-byte UTF-8 characters (like emoji 🚀, 𝕏, etc.)
        four_byte_char = "🚀"  # 4 bytes in UTF-8
        four_byte_at_limit = four_byte_char * 256  # 256 * 4 = 1024 bytes
        four_byte_over_limit = four_byte_char * 257  # 257 * 4 = 1028 bytes
        
        # Should pass at limit
        assert sanitize_s3_key(four_byte_at_limit) == four_byte_at_limit
        
        # Should fail over limit
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(four_byte_over_limit)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"

    def test_sanitize_s3_key_empty_segments(self):
        """
        Test Category 6: Empty segment handling.
        
        Tests for various ways empty segments can be created
        and how they should be handled securely.
        """
        empty_segment_cases = [
            # Multiple consecutive slashes creating empty segments
            ("folder//file.txt", "folder/file.txt"),  # Should normalize
            ("folder///file.txt", "folder/file.txt"),  # Should normalize
            ("folder////file.txt", "folder/file.txt"),  # Should normalize
            
            # Leading empty segments
            ("//folder/file.txt", "folder/file.txt"),  # Should normalize
            ("///folder/file.txt", "folder/file.txt"),  # Should normalize
            
            # Trailing empty segments
            ("folder/file.txt//", "folder/file.txt"),  # Should normalize
            ("folder/file.txt///", "folder/file.txt"),  # Should normalize
            
            # Mixed empty segments
            ("//folder//subfolder//file.txt//", "folder/subfolder/file.txt"),
            
            # Empty segments with current directory
            ("folder/./file.txt", "folder/file.txt"),  # Should normalize
            ("folder/.//file.txt", "folder/file.txt"),  # Should normalize
            
            # Complex combinations
            ("./folder//./subfolder///file.txt/", "folder/subfolder/file.txt"),
        ]
        
        for input_key, expected_output in empty_segment_cases:
            assert sanitize_s3_key(input_key) == expected_output
        
        # Cases that should fail (result in empty or invalid paths)
        invalid_empty_cases = [
            ("//", "UNSAFE_S3_KEY_PATH"),  # Only slashes
            ("///", "UNSAFE_S3_KEY_PATH"),  # Only slashes
            ("/./", "UNSAFE_S3_KEY_PATH"),  # Only current dir refs
            ("././", "UNSAFE_S3_KEY_PATH"),  # Only current dir refs
        ]
        
        for invalid_key, expected_error in invalid_empty_cases:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(invalid_key)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_drive_letter_bypass(self):
        """
        Test Category 7: Advanced drive letter bypass attempts.
        
        Tests for sophisticated attempts to bypass drive letter
        removal using various encoding and obfuscation techniques.
        """
        drive_bypass_attempts = [
            # Multiple drive letters
            ("C:D:file.txt", "D:file.txt"),  # Should remove first C: only
            ("A:B:C:file.txt", "B:C:file.txt"),  # Should remove first A: only
            
            # Drive letters with paths
            ("C:folder\\file.txt", "folder/file.txt"),  # Normal case
            ("D:..\\..\\etc\\passwd", "UNSAFE_S3_KEY_PATH"),  # Should block traversal after drive removal
            
            # Case variations
            ("c:file.txt", "file.txt"),  # Lowercase
            ("C:file.txt", "file.txt"),  # Uppercase
            
            # Drive letters in middle of path (should not be removed)
            ("folder/C:file.txt", "folder/C:file.txt"),  # Not at start, should keep
            ("data/D:backup.txt", "data/D:backup.txt"),  # Not at start, should keep
            
            # Invalid drive letters (should not match pattern)
            ("1:file.txt", "1:file.txt"),  # Number, not letter
            ("@:file.txt", "@:file.txt"),  # Symbol, not letter
            ("AA:file.txt", "AA:file.txt"),  # Too long, not drive letter
            
            # Drive letters with UNC paths
            ("C:\\\\server\\share\\file.txt", "//server/share/file.txt"),  # UNC after drive removal
        ]
        
        for input_key, expected_output in drive_bypass_attempts:
            if expected_output.startswith("UNSAFE_S3_KEY_PATH"):
                with pytest.raises(ValidationError) as exc_info:
                    sanitize_s3_key(input_key)
                assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"
            else:
                assert sanitize_s3_key(input_key) == expected_output

    def test_sanitize_s3_key_complex_traversal_sequences(self):
        """
        Test Category 8: Complex traversal sequences.
        
        Tests for sophisticated path traversal attacks using
        complex combinations of techniques and edge cases.
        """
        complex_traversal = [
            # Nested traversal attempts
            ("folder/../subfolder/../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("a/../b/../c/../d/../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            
            # Traversal with legitimate path components
            ("legitimate/folder/../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("data/backup/../../../sensitive/file.txt", "UNSAFE_S3_KEY_PATH"),
            
            # Traversal mixed with current directory
            ("folder/./../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("data/./subfolder/./../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            
            # Traversal with empty segments
            ("folder//../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("data//subfolder//../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            
            # Long traversal chains
            ("../../../../../../../../../../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("folder/" + "../" * 20 + "etc/passwd", "UNSAFE_S3_KEY_PATH"),
            
            # Traversal with Windows paths
            ("folder\\..\\..\\..\\Windows\\System32\\config", "UNSAFE_S3_KEY_PATH"),
            ("C:\\folder\\..\\..\\..\\Windows\\System32", "UNSAFE_S3_KEY_PATH"),
            
            # Traversal attempting to reach root
            ("folder/../../../../../../../", "UNSAFE_S3_KEY_PATH"),
            ("data/../../../../../../../root/.ssh/id_rsa", "UNSAFE_S3_KEY_PATH"),
            
            # Complex legitimate cases (should pass)
            ("folder/config..backup/../file.txt", "UNSAFE_S3_KEY_PATH"),  # Has traversal, should fail
            ("folder/data..old/file..backup.txt", "folder/data..old/file..backup.txt"),  # No traversal, should pass
        ]
        
        for complex_key in complex_traversal:
            if isinstance(complex_key, tuple):
                key, expected_result = complex_key
                if expected_result == "UNSAFE_S3_KEY_PATH":
                    with pytest.raises(ValidationError) as exc_info:
                        sanitize_s3_key(key)
                    assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"
                else:
                    assert sanitize_s3_key(key) == expected_result
            else:
                # All single strings in this test should raise ValidationError
                with pytest.raises(ValidationError) as exc_info:
                    sanitize_s3_key(complex_key)
                assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"

    # ========================================================================
    # PARANOID RED-TEAM LEVEL SECURITY TESTS (QA Advanced Requirements)
    # ========================================================================

    def test_sanitize_s3_key_high_unicode_codepoints(self):
        """
        Test Category 9: Very high Unicode code points.
        
        Tests characters needing surrogate pairs in UTF-16 and >4-byte 
        edge cases in UTF-8 to ensure length logic holds for all Unicode ranges.
        """
        high_unicode_cases = [
            # Mathematical script characters (surrogate pairs in UTF-16)
            ("file𝕏name.txt", "file𝕏name.txt"),  # Should pass - legitimate Unicode
            ("data𠀋file.csv", "data𠀋file.csv"),  # Should pass - CJK Extension B
            
            # Emoji and symbols requiring surrogate pairs
            ("report🚀data.txt", "report🚀data.txt"),  # Should pass - rocket emoji
            ("file💻backup.log", "file💻backup.log"),  # Should pass - computer emoji
            ("data🔒secure.txt", "data🔒secure.txt"),  # Should pass - lock emoji
            
            # Test length limits with high Unicode characters
            # Each of these characters is 4 bytes in UTF-8
            ("𝕏" * 256, "𝕏" * 256),  # 256 * 4 = 1024 bytes (at limit, should pass)
            ("🚀" * 256, "🚀" * 256),  # 256 * 4 = 1024 bytes (at limit, should pass)
        ]
        
        for input_key, expected_output in high_unicode_cases:
            assert sanitize_s3_key(input_key) == expected_output
        
        # Test cases that should fail (over byte limit)
        high_unicode_failures = [
            ("𝕏" * 257, "INVALID_S3_KEY_FORMAT"),  # 257 * 4 = 1028 bytes (over limit)
            ("🚀" * 257, "INVALID_S3_KEY_FORMAT"),  # 257 * 4 = 1028 bytes (over limit)
            ("💻" * 300, "INVALID_S3_KEY_FORMAT"),  # 300 * 4 = 1200 bytes (way over limit)
        ]
        
        for failing_key, expected_error in high_unicode_failures:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(failing_key)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_mixed_invisible_traversal(self):
        """
        Test Category 10: Mixed invisible characters with traversal attacks.
        
        Tests combinations of invisible Unicode characters with path traversal
        to ensure invisibles are caught even when mixed with other attacks.
        """
        mixed_invisible_traversal = [
            # Zero-width space mixed with traversal
            ("fo\u200Blder/../file.txt", "INVALID_S3_KEY_FORMAT"),  # Invisible in folder name
            ("folder/../fi\u200Ble.txt", "INVALID_S3_KEY_FORMAT"),  # Invisible in target file
            ("fold\u200Ber/../etc/passwd", "INVALID_S3_KEY_FORMAT"),  # Invisible + traversal
            
            # Multiple invisible characters with traversal
            ("fo\u200Bl\u200Cder/../secret.txt", "INVALID_S3_KEY_FORMAT"),  # Multiple invisibles
            ("folder/\u200B../file.txt", "INVALID_S3_KEY_FORMAT"),  # Invisible before traversal
            
            # Right-to-left override with traversal
            ("fold\u202Eer/../etc/passwd", "INVALID_S3_KEY_FORMAT"),  # RTL override + traversal
            ("folder/../\u202Dfile.txt", "INVALID_S3_KEY_FORMAT"),  # LTR override + traversal
            
            # Line separators with traversal
            ("fold\u2028er/../file.txt", "INVALID_S3_KEY_FORMAT"),  # Line separator + traversal
            ("folder/../fi\u2029le.txt", "INVALID_S3_KEY_FORMAT"),  # Paragraph separator + traversal
            
            # BOM with traversal
            ("fold\uFEFFer/../file.txt", "INVALID_S3_KEY_FORMAT"),  # BOM + traversal
            
            # Complex combinations
            ("fo\u200Bl\u202Eder/\u2028../\uFEFFfile.txt", "INVALID_S3_KEY_FORMAT"),  # Multiple types
        ]
        
        for mixed_attack, expected_error in mixed_invisible_traversal:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(mixed_attack)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_filesystem_meta_files(self):
        """
        Test Category 11: Filesystem meta-files.
        
        Tests for common filesystem metadata files that may or may not
        be desirable in archives. This establishes explicit policy.
        """
        # Policy decision: These should be ALLOWED (legitimate files)
        # Archives may legitimately contain these files
        legitimate_meta_files = [
            # macOS metadata
            (".DS_Store", ".DS_Store"),
            ("folder/.DS_Store", "folder/.DS_Store"),
            ("data/backup/.DS_Store", "data/backup/.DS_Store"),
            
            # Windows metadata
            ("Thumbs.db", "Thumbs.db"),
            ("folder/Thumbs.db", "folder/Thumbs.db"),
            ("images/Thumbs.db", "images/Thumbs.db"),
            ("desktop.ini", "desktop.ini"),
            ("folder/desktop.ini", "folder/desktop.ini"),
            
            # Linux/Unix hidden files
            (".gitignore", ".gitignore"),
            (".bashrc", ".bashrc"),
            (".profile", ".profile"),
            ("project/.gitignore", "project/.gitignore"),
            
            # IDE metadata
            (".vscode/settings.json", ".vscode/settings.json"),
            (".idea/workspace.xml", ".idea/workspace.xml"),
            
            # Package manager files
            ("package.json", "package.json"),
            ("requirements.txt", "requirements.txt"),
            ("Cargo.toml", "Cargo.toml"),
        ]
        
        for meta_file, expected_output in legitimate_meta_files:
            assert sanitize_s3_key(meta_file) == expected_output
        
        # Edge cases: Meta files with suspicious patterns should still be blocked
        suspicious_meta_files = [
            # Meta files with traversal
            ("../.DS_Store", "UNSAFE_S3_KEY_PATH"),
            ("folder/../.DS_Store", "UNSAFE_S3_KEY_PATH"),
            ("../Thumbs.db", "UNSAFE_S3_KEY_PATH"),
            
            # Meta files with control characters
            (".DS_Store\x00", "INVALID_S3_KEY_FORMAT"),
            ("Thumbs.db\x1F", "INVALID_S3_KEY_FORMAT"),
            
            # Meta files with invisible characters
            (".DS_\u200BStore", "INVALID_S3_KEY_FORMAT"),
            ("Thumbs\u200C.db", "INVALID_S3_KEY_FORMAT"),
        ]
        
        for suspicious_file, expected_error in suspicious_meta_files:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_s3_key(suspicious_file)
            assert exc_info.value.error_code == expected_error

    def test_sanitize_s3_key_extreme_segment_count(self):
        """
        Test Category 12: Extremely large number of path segments.
        
        Performance and stress test for handling many path segments
        to ensure the implementation scales reasonably.
        """
        # Test with reasonable number of segments (should pass)
        moderate_segments = "/".join([f"folder{i}" for i in range(100)]) + "/file.txt"
        result = sanitize_s3_key(moderate_segments)
        expected = "/".join([f"folder{i}" for i in range(100)]) + "/file.txt"
        assert result == expected
        
        # Test with large number of segments (should pass but test performance)
        # Each segment "dir{i}" is ~4-6 chars + 1 slash, so ~120 segments should be safe under 1024 bytes
        large_segments = "/".join([f"dir{i}" for i in range(120)]) + "/data.txt"
        result = sanitize_s3_key(large_segments)
        expected = "/".join([f"dir{i}" for i in range(120)]) + "/data.txt"
        assert result == expected
        
        # Test with extreme number of segments that would exceed byte limit
        # Each segment "d{i:03d}" is 4 chars + 1 slash = 5 bytes per segment
        # 200 segments * 5 bytes = 1000 bytes + "/file.txt" (9 bytes) = 1009 bytes (under limit)
        # Need more segments to exceed 1024 bytes: 250 segments should do it
        extreme_segments = "/".join([f"d{i:03d}" for i in range(250)]) + "/file.txt"  # Should exceed 1024 bytes
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(extreme_segments)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"
        
        # Test segments with traversal attacks (should be blocked regardless of count)
        traversal_segments = "/".join([f"folder{i}" for i in range(50)]) + "/../etc/passwd"
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(traversal_segments)
        assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"
        
        # Test empty segments in large paths (should normalize correctly)
        empty_segment_path = "//".join([f"dir{i}" for i in range(10)]) + "//file.txt"
        result = sanitize_s3_key(empty_segment_path)
        expected = "/".join([f"dir{i}" for i in range(10)]) + "/file.txt"
        assert result == expected
        
        # Performance edge case: many consecutive slashes
        many_slashes = "folder" + "/" * 100 + "file.txt"
        result = sanitize_s3_key(many_slashes)
        assert result == "folder/file.txt"

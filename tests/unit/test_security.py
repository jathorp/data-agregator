# tests/unit/test_security.py

import pytest

# Make sure your imports match your project structure
from src.data_aggregator.security import sanitize_s3_key, ValidationError


class TestSanitizeS3Key:
    """Test suite for the sanitize_s3_key security function."""

    @pytest.mark.parametrize(
        "key, expected_safe_key",
        [
            # Basic valid cases
            ("etc/passwd", "etc/passwd"),
            ("C:\\Windows\\System32.dll", "Windows/System32.dll"),
            ("foo/./bar//baz.txt", "foo/bar/baz.txt"),
            ("my-backup..old.txt", "my-backup..old.txt"),
            ("data..2024-01-01.csv", "data..2024-01-01.csv"),
            ("file...txt", "file...txt"),
            ("...hidden", "...hidden"),
            ("backup/2024/data..old/file.txt", "backup/2024/data..old/file.txt"),
            # Leading slashes should be stripped
            ("/etc/passwd", "etc/passwd"),
            # Trailing slashes should be stripped
            ("folder/sub/", "folder/sub"),
        ],
    )
    def test_sanitize_s3_key_valid_keys(self, key, expected_safe_key):
        """Test that valid S3 keys are properly sanitized."""
        assert sanitize_s3_key(key) == expected_safe_key

    @pytest.mark.parametrize(
        "invalid_key, expected_error_code",
        [
            # Path traversal attacks
            ("foo/../../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("../etc/passwd", "UNSAFE_S3_KEY_PATH"),
            ("folder/../secret.txt", "UNSAFE_S3_KEY_PATH"),

            # Size violation
            ("a" * 1025, "INVALID_S3_KEY_LENGTH"),

            # Character violations
            ("file\x00name.txt", "INVALID_S3_KEY_CHARACTER"),
            ("file\x1fname.txt", "INVALID_S3_KEY_CHARACTER"),
            ("file\u200Bname.txt", "INVALID_S3_KEY_CHARACTER"),  # Zero-width space

            # Format violations
            ("", "INVALID_S3_KEY_FORMAT"),
            (" folder/file.txt", "INVALID_S3_KEY_FORMAT"),  # Leading whitespace in component

            # Paths that resolve to empty
            (".", "UNSAFE_S3_KEY_PATH"),
            ("/", "UNSAFE_S3_KEY_PATH"),
            ("//", "UNSAFE_S3_KEY_PATH"),

            # Type violations
            (123, "INVALID_S3_KEY_TYPE"),
            (None, "INVALID_S3_KEY_TYPE"),
            ([], "INVALID_S3_KEY_TYPE"),
        ],
    )
    def test_sanitize_s3_key_invalid_keys_parametrized(self, invalid_key, expected_error_code):
        """Test a variety of invalid S3 keys raise ValidationError with correct error codes."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(invalid_key)
        assert exc_info.value.error_code == expected_error_code

    @pytest.mark.parametrize("dangerous_path", [
        "folder/../etc/passwd",
        "../secret.txt",
        "foo/../bar",
        "../../etc/shadow",
    ])
    def test_sanitize_s3_key_blocks_path_traversal(self, dangerous_path):
        """Ensure path traversal attacks are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(dangerous_path)
        assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"

    @pytest.mark.parametrize("char_code", [0x00, 0x01, 0x07, 0x0A, 0x1F, 0x7F])
    def test_sanitize_s3_key_blocks_control_characters(self, char_code):
        """Test that all control characters are properly blocked."""
        char = chr(char_code)
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(f"file{char}name.txt")
        assert exc_info.value.error_code == "INVALID_S3_KEY_CHARACTER"

    def test_sanitize_s3_key_utf8_length_limit(self):
        """Test UTF-8 byte length validation after normalization."""
        # Test with multi-byte UTF-8 characters
        # 'é' is 2 bytes. 513 * 2 = 1026 bytes (over limit)
        multi_byte_over = "é" * 513
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(multi_byte_over)
        assert exc_info.value.error_code == "INVALID_S3_KEY_LENGTH"

    @pytest.mark.parametrize("invisible_char", [
        "\u200B", "\u200C", "\u200D", "\uFEFF",  # Zero-width
        "\u202E", "\u202D", "\u202C",  # Directional
    ])
    def test_sanitize_s3_key_blocks_unicode_format_chars(self, invisible_char):
        """Test that dangerous Unicode format characters are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(f"file{invisible_char}name.txt")
        assert exc_info.value.error_code == "INVALID_S3_KEY_CHARACTER"

    @pytest.mark.parametrize("whitespace_key", [
        " filename.txt", "filename.txt ",
        "folder/ file.txt", "folder /filename.txt",
    ])
    def test_sanitize_s3_key_blocks_leading_trailing_spaces(self, whitespace_key):
        """Test leading/trailing whitespace in components is blocked."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(whitespace_key)
        assert exc_info.value.error_code == "INVALID_S3_KEY_FORMAT"

    @pytest.mark.parametrize("device_name", [
        "CON", "PRN", "AUX", "NUL", "COM1", "LPT1",
        "con", "Con.txt", "folder/PRN",
    ])
    def test_sanitize_s3_key_blocks_windows_device_names(self, device_name):
        """Test for Windows reserved device names."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(device_name)
        assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"

    @pytest.mark.parametrize("mixed_attack", [
        "folder\\..\\..\\etc\\passwd",
        "folder%2F..%2F..%2Fetc%2Fpasswd",
        "folder%252F..%252F..%252Fetc%252Fpasswd",  # Double encoded
        "folder/\uFF0E\uFF0E/etc/passwd",  # Fullwidth dots (will be normalized)
    ])
    def test_sanitize_s3_key_blocks_mixed_traversal_attempts(self, mixed_attack):
        """Test for sophisticated path traversal attacks."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(mixed_attack)
        assert exc_info.value.error_code == "UNSAFE_S3_KEY_PATH"

    def test_sanitize_s3_key_high_unicode_codepoints(self):
        """Test that high Unicode code points are handled correctly."""
        # NFKC normalization will change 𝕏 to X. This is an acceptable
        # security trade-off to catch more homoglyph attacks.
        assert sanitize_s3_key("file𝕏name.txt") == "fileXname.txt"
        # Emoji are unaffected by NFKC.
        assert sanitize_s3_key("report🚀data.txt") == "report🚀data.txt"

        # Test length limits with 4-byte UTF-8 characters
        # 256 * 4 = 1024 bytes (at limit)
        at_limit = "🚀" * 256
        assert sanitize_s3_key(at_limit) == at_limit

        # 257 * 4 = 1028 bytes (over limit)
        over_limit = "🚀" * 257
        with pytest.raises(ValidationError) as exc_info:
            sanitize_s3_key(over_limit)
        assert exc_info.value.error_code == "INVALID_S3_KEY_LENGTH"
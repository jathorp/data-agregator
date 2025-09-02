"""
Security utilities for the Data Aggregator service.

This module provides security-critical functions for sanitizing and validating
file paths and S3 keys to prevent various classes of attacks when creating
and extracting compressed archives.

The primary focus is preventing:
- Path traversal attacks (../../../etc/passwd), including encoded variations.
- Zip bomb/tar bomb attacks that could overwrite system files.
- Cross-platform path manipulation vulnerabilities (Windows paths, reserved names).
- Unicode-based obfuscation and invisible character attacks.
"""

import re
import unicodedata
import urllib.parse
from typing import Set

# Assuming a custom exception class is defined elsewhere in the project
class ValidationError(ValueError):
    """Custom exception for validation errors."""
    def __init__(self, message, error_code=None, context=None):
        super().__init__(message)
        self.error_code = error_code
        self.context = context or {}

# --- Module-level constants for performance and clarity ---

# Matches Windows drive letters like C: at the start of a string
_DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")

# C0 control characters (0x00-0x1F) and DEL (0x7F)
_INVALID_CONTROL_CHARS: Set[int] = set(range(0x20)) | {0x7F}

# Advanced security: Unicode format characters (Cf category) that are always problematic.
# This is more robust than a fixed list of invisibles.
# Includes directional overrides, zero-width joiners, etc.
_UNICODE_FORMAT_CHAR_CATEGORIES: Set[str] = {"Cf"}

# Windows reserved device names (case-insensitive check)
_WINDOWS_DEVICE_NAMES: Set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}


def sanitize_s3_key(key: str) -> str:
    """
    Sanitize and validate an S3 key for secure use in archives.

    This function follows a strict "canonicalize first, then validate" approach
    to prevent multiple classes of security vulnerabilities:

    1.  **Canonicalization**:
        -   Recursively URL-decodes the key to reveal any hidden traversal sequences.
        -   Normalizes Unicode characters (NFKC) to collapse visual ambiguities
            (e.g., full-width dots) into standard ASCII equivalents.
        -   Normalizes path separators to POSIX standard (`/`).
        -   Strips Windows drive letters (`C:`).

    2.  **Validation**:
        -   Enforces S3's UTF-8 byte length limit (1024).
        -   Blocks null bytes, control characters, and dangerous Unicode format characters.
        -   Prevents path traversal (`..`) as a distinct path component.
        -   Blocks Windows reserved device names (e.g., `CON`, `PRN`).
        -   Rejects leading/trailing whitespace in path components.
        -   Disallows absolute paths and redundant segments (`/`, `.`, `//`).

    Args:
        key: The S3 object key to sanitize.

    Returns:
        A safe, normalized POSIX path suitable for use in archives.

    Raises:
        ValidationError: If the key is invalid or contains any security risks.

    Examples:
        >>> sanitize_s3_key("folder/file.txt")
        'folder/file.txt'

        >>> sanitize_s3_key("C:\\Users\\test.csv")
        'Users/test.csv'

        >>> sanitize_s3_key("..%2F..%2Fetc/passwd") # URL-encoded traversal
        ValidationError: S3 key contains path traversal...

        >>> sanitize_s3_key("folder/../secrets.txt") # Standard traversal
        ValidationError: S3 key contains path traversal...

        >>> sanitize_s3_key("my-backup..old.txt")  # '..' in filename is OK
        'my-backup..old.txt'

        >>> sanitize_s3_key("/absolute/path/file") # Absolute paths are made relative
        'absolute/path/file'

        >>> sanitize_s3_key(" a / b ") # Whitespace in segments is blocked
        ValidationError: S3 key component contains leading or trailing whitespace...
    """
    # 1. PRE-VALIDATION AND CANONICALIZATION
    if not isinstance(key, str):
        raise ValidationError(
            "S3 key must be a string.",
            error_code="INVALID_S3_KEY_TYPE",
            context={"key_type": type(key).__name__}
        )

    if not key:
        raise ValidationError(
            "S3 key cannot be empty.",
            error_code="INVALID_S3_KEY_FORMAT"
        )

    # -- Start Canonicalization --
    decoded_key = key
    for _ in range(5):
        unquoted = urllib.parse.unquote(decoded_key)
        if unquoted == decoded_key:
            break
        decoded_key = unquoted

    try:
        normalized_key = unicodedata.normalize('NFKC', decoded_key)
    except Exception:
        raise ValidationError(
            "S3 key contains invalid Unicode sequences.",
            error_code="INVALID_S3_KEY_UNICODE",
            context={"key": decoded_key}
        )

    # -- All canonicalization is done. Now, start validation. --

    # 2. VALIDATION OF THE CANONICAL KEY

    # CRITICAL: Check length AFTER normalization.
    if len(normalized_key.encode("utf-8")) > 1024:
        raise ValidationError(
            "S3 key exceeds 1024-byte UTF-8 limit.",
            error_code="INVALID_S3_KEY_LENGTH",
            context={"key": key, "normalized_key": normalized_key}
        )

    posix_key = normalized_key.replace("\\", "/")
    safe_key = _DRIVE_PREFIX.sub("", posix_key)

    for char in safe_key:
        code = ord(char)
        if code == 0x00:
            raise ValidationError(
                "S3 key contains null byte.",
                error_code="INVALID_S3_KEY_CHARACTER",
                context={"key": safe_key}
            )
        if code in _INVALID_CONTROL_CHARS:
            raise ValidationError(
                "S3 key contains invalid control characters.",
                error_code="INVALID_S3_KEY_CHARACTER",
                context={"key": safe_key, "char_code": hex(code)}
            )
        if unicodedata.category(char) in _UNICODE_FORMAT_CHAR_CATEGORIES:
            raise ValidationError(
                "S3 key contains invalid Unicode format characters.",
                error_code="INVALID_S3_KEY_CHARACTER",
                context={"key": safe_key, "char_code": hex(code)}
            )

    # 3. PATH COMPONENT VALIDATION AND FINAL ASSEMBLY
    safe_components = []
    for part in safe_key.split('/'):
        if part in {"", "."}:
            continue

        if part == "..":
            raise ValidationError(
                "S3 key contains path traversal sequence ('..').",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "normalized_key": safe_key}
            )

        if part.strip() != part:
            raise ValidationError(
                "S3 key component contains leading or trailing whitespace.",
                error_code="INVALID_S3_KEY_FORMAT",
                context={"key": key, "component": part}
            )

        base_name = part.split(".", 1)[0].upper()
        if base_name in _WINDOWS_DEVICE_NAMES:
            raise ValidationError(
                "S3 key contains a Windows reserved device name.",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "device_name": part}
            )

        safe_components.append(part)

    final_path = "/".join(safe_components)

    if not final_path:
        raise ValidationError(
            "S3 key resolves to an empty or invalid path.",
            error_code="UNSAFE_S3_KEY_PATH",
            context={"key": key, "normalized_key": safe_key}
        )

    return final_path
"""
Security utilities for the Data Aggregator service.

This module provides security-critical functions for sanitizing and validating
file paths and S3 keys to prevent various classes of attacks when creating
and extracting compressed archives.

The primary focus is preventing:
- Path traversal attacks (../../../etc/passwd)
- Zip bomb/tar bomb attacks that could overwrite system files
- Cross-platform path manipulation vulnerabilities
"""

import re
from pathlib import PurePosixPath
from typing import Set

from .exceptions import ValidationError

# Module-level constants for improved performance
_DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")
_INVALID_CONTROL_CHARS: Set[int] = set(range(0x00, 0x20)) | {0x7F}  # includes DEL


def sanitize_s3_key(key: str) -> str:
    """
    Sanitize and validate S3 keys for secure archive creation and extraction.
    
    This function prevents multiple classes of security vulnerabilities:
    
    1. **Path Traversal Attacks**: Blocks attempts to escape intended directories
       using sequences like '../../../etc/passwd' by checking for '..' as 
       separate path segments (not within filenames)
    
    2. **Zip Bomb/Tar Bomb Protection**: Ensures generated archives cannot 
       overwrite system files when extracted by consumers. This is critical
       for preventing malicious archives from compromising extraction systems.
    
    3. **Cross-Platform Safety**: Normalizes Windows paths to POSIX format
       and removes drive letters to prevent platform-specific attacks
    
    4. **Control Character Prevention**: Blocks binary and control characters
       that could cause issues in file systems or terminals
    
    The function performs strict validation and normalization to ensure
    that any tar.gz files we create can be safely extracted without
    security risks.
    
    Args:
        key: The S3 object key to sanitize
        
    Returns:
        A safe, normalized POSIX path suitable for use in archives
        
    Raises:
        ValidationError: If the key contains security risks or is invalid
        
    Examples:
        >>> sanitize_s3_key("folder/file.txt")
        "folder/file.txt"
        
        >>> sanitize_s3_key("C:\\Windows\\file.txt")
        "Windows/file.txt"
        
        >>> sanitize_s3_key("my-backup..old.txt")  # ".." in filename is OK
        "my-backup..old.txt"
        
        >>> sanitize_s3_key("folder/../etc/passwd")  # Path traversal blocked
        ValidationError: S3 key contains path traversal...
    """
    
    # Type check
    if not isinstance(key, str):
        raise ValidationError(
            "S3 key is not a valid string",
            error_code="INVALID_S3_KEY_TYPE",
            context={"key": key, "type": type(key).__name__}
        )

    # UTF-8 length check (S3 limit is 1024 bytes in UTF-8)
    utf8_bytes = key.encode("utf-8")
    if len(utf8_bytes) > 1024:
        raise ValidationError(
            "S3 key exceeds byte length limit",
            error_code="INVALID_S3_KEY_FORMAT",
            context={"key": key, "key_length": len(utf8_bytes)}
        )

    # Control character check - prevents binary/control chars that could
    # cause issues in file systems or when displayed in terminals
    if any(ord(c) in _INVALID_CONTROL_CHARS for c in key):
        raise ValidationError(
            "S3 key contains invalid control characters",
            error_code="INVALID_S3_KEY_FORMAT",
            context={"key": key}
        )

    # Remove Windows drive letter (C:, D:, etc.) for cross-platform safety
    key_no_drive = _DRIVE_PREFIX.sub("", key)

    # Convert backslashes to forward slashes for POSIX compatibility
    key_posix = key_no_drive.replace("\\", "/")

    # SECURITY CRITICAL: Check for path traversal attacks
    # We check for ".." as separate path segments, not within filenames
    # This allows legitimate filenames like "my-backup..old.txt" while
    # blocking actual path traversal like "folder/../etc/passwd"
    if any(part == ".." for part in key_posix.split("/")):
        raise ValidationError(
            "S3 key contains path traversal or invalid path components",
            error_code="UNSAFE_S3_KEY_PATH",
            context={"key": key, "normalized_path": key_posix}
        )

    # Normalize path - remove empty segments and current directory references
    # but preserve legitimate filenames containing dots
    path_parts = []
    for part in key_posix.split('/'):
        if part and part != '.':
            path_parts.append(part)
    
    safe_path = '/'.join(path_parts)

    # Remove exactly one leading slash if present (S3 keys should be relative)
    if safe_path.startswith("/"):
        safe_path = safe_path[1:]

    # Final validation - ensure we don't have empty or current directory paths
    if safe_path in {"", "."}:
        raise ValidationError(
            "S3 key contains path traversal or invalid path components",
            error_code="UNSAFE_S3_KEY_PATH",
            context={"key": key, "normalized_path": safe_path}
        )

    return safe_path

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
import unicodedata
import urllib.parse
from pathlib import PurePosixPath

from .exceptions import ValidationError

# Module-level constants for improved performance
_DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")
_INVALID_CONTROL_CHARS: set[int] = set(range(0x00, 0x20)) | {0x7F}  # includes DEL

# Advanced security constants for paranoid red-team level protection
_UNICODE_INVISIBLES: set[int] = {
    # Zero-width characters
    0x200B,  # Zero Width Space
    0x200C,  # Zero Width Non-Joiner
    0x200D,  # Zero Width Joiner
    0xFEFF,  # Zero Width No-Break Space (BOM)
    
    # Directional override characters
    0x202E,  # Right-to-Left Override
    0x202D,  # Left-to-Right Override
    0x202C,  # Pop Directional Formatting
    
    # Line/paragraph separators
    0x2028,  # Line Separator
    0x2029,  # Paragraph Separator
    
    # Other problematic Unicode
    0x00A0,  # Non-breaking space
    0x1680,  # Ogham space mark
}

# Windows reserved device names (case-insensitive)
_WINDOWS_DEVICE_NAMES: set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# Unicode variations of dots for traversal detection (excluding normal ASCII dots)
_UNICODE_DOTS: set[str] = {
    "\uFF0E\uFF0E",  # Fullwidth dots (not ASCII)
    "\u3002\u3002",  # Ideographic full stops
    "\u2024\u2024",  # One dot leaders
    "\u2027\u2027",  # Hyphenation points
    "\uFF61\uFF61",  # Halfwidth ideographic periods
}

# URL encoding patterns for traversal detection
_URL_TRAVERSAL_PATTERNS = re.compile(r"%2[Ff]|%5[Cc]|%252[Ff]|%252[Ee]")


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

    # ADVANCED SECURITY: Unicode invisible character detection
    # Use both hardcoded list and unicodedata for comprehensive detection
    # but be more selective to avoid false positives
    for char in key:
        char_code = ord(char)
        # Check hardcoded invisibles first (known problematic characters)
        if char_code in _UNICODE_INVISIBLES:
            raise ValidationError(
                "S3 key contains invalid Unicode invisible characters",
                error_code="INVALID_S3_KEY_FORMAT",
                context={"key": key, "char": char, "char_code": hex(char_code)}
            )
        
        # Additional check for format characters (Cf category) - these are always problematic
        char_category = unicodedata.category(char)
        if char_category == "Cf":
            raise ValidationError(
                "S3 key contains invalid Unicode invisible characters",
                error_code="INVALID_S3_KEY_FORMAT",
                context={"key": key, "char": char, "char_code": hex(char_code)}
            )

    # ADVANCED SECURITY: Leading/trailing whitespace detection
    # Blocks spaces and tabs at start/end of key or path segments
    if key != key.strip() or any(part != part.strip() for part in key.split("/")):
        raise ValidationError(
            "S3 key contains leading or trailing whitespace",
            error_code="INVALID_S3_KEY_FORMAT",
            context={"key": key}
        )

    # Remove Windows drive letter (C:, D:, etc.) for cross-platform safety
    key_no_drive = _DRIVE_PREFIX.sub("", key)

    # Convert backslashes to forward slashes for POSIX compatibility
    key_posix = key_no_drive.replace("\\", "/")

    # ADVANCED SECURITY: Windows device name detection (refined to avoid over-blocking)
    # Check each path segment for Windows reserved device names
    for part in key_posix.split("/"):
        if part:  # Skip empty segments
            # Split on first dot only to handle extensions properly
            if "." in part:
                base_name = part.split(".", 1)[0].upper()
            else:
                base_name = part.upper()
            
            # Only block if it's exactly a device name (not a substring)
            if base_name in _WINDOWS_DEVICE_NAMES:
                raise ValidationError(
                    "S3 key contains Windows reserved device name",
                    error_code="UNSAFE_S3_KEY_PATH",
                    context={"key": key, "device_name": part}
                )

    # ADVANCED SECURITY: Unicode dots traversal detection
    # Check for Unicode variations of ".." that could bypass normal detection
    # Only check for non-ASCII Unicode dots to avoid false positives
    if any(unicode_dots in key_posix for unicode_dots in _UNICODE_DOTS):
        raise ValidationError(
            "S3 key contains Unicode path traversal sequences",
            error_code="UNSAFE_S3_KEY_PATH",
            context={"key": key, "normalized_path": key_posix}
        )

    # ADVANCED SECURITY: URL encoding traversal detection with recursive unquote
    # Recursively decode URL encoding until stable to catch nested encodings
    decoded_key = key_posix
    max_iterations = 5  # Prevent infinite loops
    for _ in range(max_iterations):
        try:
            new_decoded = urllib.parse.unquote(decoded_key)
            if new_decoded == decoded_key:
                break  # No more changes, we're stable
            decoded_key = new_decoded
        except Exception:
            break  # Stop on any decoding errors
    
    # Check if decoded version contains traversal patterns
    if decoded_key != key_posix:
        # Convert backslashes to forward slashes in decoded version too
        decoded_normalized = decoded_key.replace("\\", "/")
        
        # Re-run all security checks on the decoded version
        if any(part == ".." for part in decoded_normalized.split("/")):
            raise ValidationError(
                "S3 key contains URL-encoded path traversal sequences",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "decoded_key": decoded_key}
            )
        
        # Check for Unicode dots in decoded version
        if any(unicode_dots in decoded_normalized for unicode_dots in _UNICODE_DOTS):
            raise ValidationError(
                "S3 key contains URL-encoded Unicode path traversal sequences",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "decoded_key": decoded_key}
            )

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

    # Use PurePosixPath for robust, platform-agnostic path normalization
    # This handles edge cases better than manual string manipulation
    try:
        # Check for UNC path before normalization
        original_had_drive = _DRIVE_PREFIX.match(key)
        is_unc_path = (original_had_drive and 
                       key_posix.startswith("//") and 
                       not key_posix.startswith("///") and  # Not triple slash
                       key_posix.count('//') == 1 and  # Only one double slash at start
                       key_posix.index('//') == 0)  # Double slash is at the beginning
        
        if is_unc_path:
            # For UNC paths, preserve the leading double slash
            unc_parts = key_posix[2:].split('/')  # Remove leading //
            unc_parts = [p for p in unc_parts if p and p != '.']
            if len(unc_parts) >= 2:  # Must have server and share at minimum
                safe_path = "//" + "/".join(unc_parts)
            else:
                raise ValidationError(
                    "Invalid UNC path structure",
                    error_code="UNSAFE_S3_KEY_PATH",
                    context={"key": key, "normalized_path": key_posix}
                )
        else:
            # Use PurePosixPath for standard path normalization
            # But handle the leading slash removal manually for better control
            normalized_path = PurePosixPath(key_posix)
            safe_path = str(normalized_path)
            
            # Handle special case where "//" becomes just "/" after normalization
            if safe_path == "/":
                raise ValidationError(
                    "S3 key contains path traversal or invalid path components",
                    error_code="UNSAFE_S3_KEY_PATH",
                    context={"key": key, "normalized_path": safe_path}
                )
            
            # Remove leading slash for S3 keys (should be relative)
            while safe_path.startswith("/"):
                safe_path = safe_path[1:]
        
        # Final validation - ensure we don't have empty or current directory paths
        if safe_path in {"", ".", "//"}:
            raise ValidationError(
                "S3 key contains path traversal or invalid path components",
                error_code="UNSAFE_S3_KEY_PATH",
                context={"key": key, "normalized_path": safe_path}
            )
            
    except Exception as e:
        # If PurePosixPath fails, it's likely a malformed path
        if isinstance(e, ValidationError):
            raise  # Re-raise our own validation errors
        raise ValidationError(
            "S3 key contains invalid path structure",
            error_code="INVALID_S3_KEY_FORMAT",
            context={"key": key, "error": str(e)}
        )

    return safe_path

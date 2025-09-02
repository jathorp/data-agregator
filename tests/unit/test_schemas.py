# tests/unit/test_schemas.py

import pytest
import pydantic

# Assuming this is the new structure in schemas.py
from src.data_aggregator.schemas import S3EventNotificationRecord


class TestS3EventNotificationRecord:
    """Test suite for the S3EventNotificationRecord Pydantic model."""

    def test_valid_s3_event_record_preserves_original_key(self):
        """
        Test that a well-formed record is parsed successfully AND that the
        original key is preserved even after sanitization.
        """
        original_key = "C:\\Users\\file..name.txt"
        sanitized_key = "Users/file..name.txt"

        raw_record = {
            "s3": {
                "bucket": {"name": "my-source-bucket"},
                "object": {
                    "key": original_key,
                    "size": 1234,
                    "versionId": "abc-123",
                    "sequencer": "0055AED4D224A8D1",  # <-- ADDED
                }
            }
        }

        parsed = S3EventNotificationRecord.model_validate(raw_record)

        assert parsed.s3.object.key == sanitized_key
        assert parsed.s3.object.original_key == original_key
        assert parsed.s3.bucket.name == "my-source-bucket"
        assert parsed.s3.object.size == 1234
        assert parsed.s3.object.version_id == "abc-123"
        assert parsed.s3.object.sequencer == "0055AED4D224A8D1"  # <-- ADDED ASSERTION

    def test_s3_event_record_without_version_id(self):
        """Test that a record without an optional versionId is still valid."""
        raw_record = {
            "s3": {
                "bucket": {"name": "my-source-bucket"},
                "object": {
                    "key": "another/file.txt",
                    "size": 5678,
                    "sequencer": "0055AED4D224A8D2",  # <-- ADDED
                }
            }
        }

        parsed = S3EventNotificationRecord.model_validate(raw_record)
        assert parsed.s3.object.key == "another/file.txt"
        assert parsed.s3.object.version_id is None

    def test_invalid_s3_key_raises_pydantic_validation_error(self):
        """
        Test that an unsafe key causes a Pydantic ValidationError.
        """
        malicious_record = {
            "s3": {
                "bucket": {"name": "my-source-bucket"},
                "object": {
                    "key": "folder/../../etc/passwd",
                    "size": 100,
                    "sequencer": "0055AED4D224A8D3",  # <-- ADDED
                }
            }
        }

        with pytest.raises(pydantic.ValidationError) as exc_info:
            S3EventNotificationRecord.model_validate(malicious_record)

        errors = exc_info.value.errors()
        # The only error should be the key validation, not a missing sequencer.
        assert len(errors) == 1
        error_details = errors[0]
        assert error_details["loc"] == ('s3', 'object', 'key')
        assert "S3 key contains path traversal" in str(error_details["msg"])

    @pytest.mark.parametrize("invalid_record, expected_loc", [
        # ... (tests for missing fields are still correct and don't need sequencer) ...
        # Add a test for a missing sequencer
        ({"s3": {"bucket": {"name": "b"}, "object": {"key": "k", "size": 1}}}, ('s3', 'object', 'sequencer')),
        # ... (tests for wrong types are also correct) ...
    ])
    def test_malformed_structure_raises_validation_error(self, invalid_record, expected_loc):
        """Test that various structural malformations raise a ValidationError."""
        with pytest.raises(pydantic.ValidationError) as exc_info:
            S3EventNotificationRecord.model_validate(invalid_record)

        errors = exc_info.value.errors()
        error_locations = [e['loc'] for e in errors]
        assert expected_loc in error_locations

    def test_pydantic_coerces_valid_types(self):
        """Test that Pydantic correctly coerces types where it can."""
        record = {
            "s3": {
                "bucket": {"name": "my-bucket"},
                "object": {
                    "key": "file.txt",
                    "size": "1234",
                    "sequencer": "0055AED4D224A8D4",  # <-- ADDED
                }
            }
        }
        parsed = S3EventNotificationRecord.model_validate(record)
        assert isinstance(parsed.s3.object.size, int)
        assert parsed.s3.object.size == 1234
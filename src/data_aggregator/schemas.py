# In src/data_aggregator/schemas.py

from typing import TypedDict
from pydantic import BaseModel, Field, field_validator, PrivateAttr

from .security import sanitize_s3_key
from .exceptions import ValidationError as CustomValidationError

# --- Static Type Hinting (for mypy and IDEs) ---


class S3BucketDict(TypedDict):
    name: str


class S3ObjectDict(TypedDict):
    key: str
    size: int
    versionId: str | None
    sequencer: str


class S3DataDict(TypedDict):
    bucket: S3BucketDict
    object: S3ObjectDict


class S3EventRecord(TypedDict):
    """
    A TypedDict representing the structure of a single S3 event record.
    Used for static type analysis throughout the application.
    """

    s3: S3DataDict


# --- Runtime Validation (using Pydantic) ---


class S3BucketModel(BaseModel):
    name: str = Field(..., min_length=1)


class S3ObjectModel(BaseModel):
    # This will hold the original, unmodified key
    _original_key: str = PrivateAttr()

    key: str = Field(..., min_length=1)
    size: int
    version_id: str | None = Field(None, alias="versionId")
    sequencer: str

    def __init__(self, **data):
        super().__init__(**data)
        # Store the original key before it gets sanitized
        self._original_key = data.get("key", "")

    # This validator now modifies the 'key' attribute, but the original
    # is safely stored in '_original_key'.
    @field_validator("key")
    @classmethod
    def validate_s3_key_security(cls, value: str) -> str:
        try:
            return sanitize_s3_key(value)
        except CustomValidationError as e:
            raise ValueError(str(e))

    @property
    def original_key(self) -> str:
        return self._original_key


class S3DataModel(BaseModel):
    bucket: S3BucketModel
    object: S3ObjectModel


class S3EventNotificationRecord(BaseModel):
    """
    Pydantic model for runtime parsing and validation of an S3 event record.
    """

    s3: S3DataModel

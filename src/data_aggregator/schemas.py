# src/data_aggregator/schemas.py

"""
Shared data schemas and type definitions for the Data Aggregator service.

This module centralizes the data structures used across the application, primarily
for parsing the S3 event notification record. Using a central schema file:
  - Improves type safety and enables static analysis.
  - Prevents circular import errors between modules.
  - Serves as clear documentation for the expected data shapes.
"""

from typing import TypedDict


class S3Object(TypedDict):
    """Represents the 'object' portion of an S3 event record."""

    key: str
    size: int


class S3Bucket(TypedDict):
    """Represents the 'bucket' portion of an S3 event record."""

    name: str


class S3Entity(TypedDict):
    """Represents the 's3' entity containing bucket and object details."""

    bucket: S3Bucket
    object: S3Object


class S3EventRecord(TypedDict):
    """Represents the top-level structure of a single S3 event record."""

    s3: S3Entity

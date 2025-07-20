# e2e_tests/components/data_generator.py

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class DataGenerator(ABC):
    """Abstract base class for data generation strategies."""

    @abstractmethod
    def generate(self, path: Path, size_mb: int) -> str:
        """Generates a file at the given path and returns its SHA256 hash."""
        pass


class RandomDataGenerator(DataGenerator):
    """Generates incompressible, cryptographically random data."""

    def generate(self, path: Path, size_mb: int) -> str:
        hasher = hashlib.sha256()
        if size_mb == 0:
            path.touch()
            return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        with open(path, "wb") as f:
            for _ in range(size_mb):
                chunk = os.urandom(CHUNK_SIZE)
                f.write(chunk)
                hasher.update(chunk)
        return hasher.hexdigest()


class CompressibleTextGenerator(DataGenerator):
    """Generates highly compressible, repetitive text data."""

    def generate(self, path: Path, size_mb: int) -> str:
        hasher = hashlib.sha256()
        if size_mb == 0:
            path.touch()
            return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        compressible_sentence = (
            "This is a highly repetitive sentence that is designed to test the "
            "compression efficiency of the data aggregator pipeline. "
        ).encode("utf-8")
        sentence_len = len(compressible_sentence)
        target_bytes = size_mb * CHUNK_SIZE

        with open(path, "wb") as f:
            bytes_written = 0
            while bytes_written < target_bytes:
                f.write(compressible_sentence)
                hasher.update(compressible_sentence)
                bytes_written += sentence_len
        return hasher.hexdigest()

# tests/unit/test_config.py

import pytest

# Import the components to be tested
from src.data_aggregator.config import ConfigurationError, get_config


@pytest.fixture(autouse=True)
def clear_config_cache():
    """
    Fixture to automatically clear the lru_cache for get_config before each test.
    This ensures that each test gets a fresh configuration object based on its
    own monkeypatched environment, providing perfect test isolation.
    """
    get_config.cache_clear()


@pytest.fixture
def mock_valid_env(monkeypatch):
    """Sets a valid environment for a single test."""
    monkeypatch.setenv("DISTRIBUTION_BUCKET_NAME", "test-dist-bucket")
    monkeypatch.setenv("SERVICE_NAME", "test-service")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "test-idempotency-table")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("IDEMPOTENCY_TTL_DAYS", "14")
    monkeypatch.setenv("MAX_BUNDLE_INPUT_MB", "50")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


def test_get_config_happy_path(mock_valid_env):
    """Tests that configuration loads correctly when all env vars are set."""
    # ACT: Call the factory function
    config = get_config()

    # ASSERT
    assert config.distribution_bucket == "test-dist-bucket"
    assert config.service_name == "test-service"
    assert config.idempotency_table == "test-idempotency-table"
    assert config.environment == "test"
    assert config.idempotency_ttl_days == 14
    assert config.max_bundle_input_mb == 50
    assert config.log_level == "DEBUG"
    assert config.idempotency_ttl_seconds == 14 * 86_400


def test_get_config_uses_defaults(monkeypatch):
    """Tests that optional variables fall back to their default values."""
    # ARRANGE: Set only the required variables
    monkeypatch.setenv("DISTRIBUTION_BUCKET_NAME", "test-dist-bucket")
    monkeypatch.setenv("SERVICE_NAME", "test-service")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "test-idempotency-table")
    monkeypatch.setenv("ENVIRONMENT", "prod")  # This is required, so we must set it

    # Ensure optional variables are not set
    monkeypatch.delenv("IDEMPOTENCY_TTL_DAYS", raising=False)
    monkeypatch.delenv("MAX_BUNDLE_INPUT_MB", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
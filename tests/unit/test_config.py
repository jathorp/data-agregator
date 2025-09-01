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
    # Set the new configuration fields
    monkeypatch.setenv("SPOOL_FILE_MAX_SIZE_MB", "32")
    monkeypatch.setenv("TIMEOUT_GUARD_THRESHOLD_SECONDS", "5")
    monkeypatch.setenv("MAX_BUNDLE_ON_DISK_MB", "200")


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
    # Test new configuration fields
    assert config.spool_file_max_size_mb == 32
    assert config.timeout_guard_threshold_seconds == 5
    assert config.max_bundle_on_disk_mb == 200
    # Test derived properties
    assert config.spool_file_max_size_bytes == 32 * 1024 * 1024
    assert config.timeout_guard_threshold_ms == 5 * 1000
    assert config.max_bundle_on_disk_bytes == 200 * 1024 * 1024


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
    monkeypatch.delenv("SPOOL_FILE_MAX_SIZE_MB", raising=False)
    monkeypatch.delenv("TIMEOUT_GUARD_THRESHOLD_SECONDS", raising=False)
    monkeypatch.delenv("MAX_BUNDLE_ON_DISK_MB", raising=False)

    # ACT
    config = get_config()

    # ASSERT: Check that defaults are used
    assert config.idempotency_ttl_days == 7  # Default
    assert config.max_bundle_input_mb == 100  # Default
    assert config.log_level == "INFO"  # Default
    # Test new configuration field defaults
    assert config.spool_file_max_size_mb == 64  # Default
    assert config.timeout_guard_threshold_seconds == 10  # Default
    assert config.max_bundle_on_disk_mb == 400  # Default
    # Test derived properties with defaults
    assert config.spool_file_max_size_bytes == 64 * 1024 * 1024
    assert config.timeout_guard_threshold_ms == 10 * 1000
    assert config.max_bundle_on_disk_bytes == 400 * 1024 * 1024


def test_get_config_missing_required_env_var(monkeypatch):
    """Tests that ConfigurationError is raised when required env vars are missing."""
    # ARRANGE: Don't set any environment variables
    monkeypatch.delenv("DISTRIBUTION_BUCKET_NAME", raising=False)
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    monkeypatch.delenv("IDEMPOTENCY_TABLE_NAME", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    # ACT & ASSERT
    with pytest.raises(ConfigurationError):
        get_config()


def test_get_config_invalid_integer_env_var(monkeypatch):
    """Tests that ConfigurationError is raised for invalid integer values."""
    # ARRANGE: Set required vars but make an optional integer invalid
    monkeypatch.setenv("DISTRIBUTION_BUCKET_NAME", "test-dist-bucket")
    monkeypatch.setenv("SERVICE_NAME", "test-service")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "test-idempotency-table")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("IDEMPOTENCY_TTL_DAYS", "not-a-number")

    # ACT & ASSERT
    with pytest.raises(ConfigurationError):
        get_config()


def test_get_config_caching():
    """Tests that get_config returns the same instance when called multiple times."""
    # ACT
    config1 = get_config()
    config2 = get_config()

    # ASSERT
    assert config1 is config2  # Same object instance due to lru_cache

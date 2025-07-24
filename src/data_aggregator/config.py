import logging
import os
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""

    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Application configuration loaded from environment variables."""

    # --- Required Variables ---
    distribution_bucket: str
    service_name: str
    environment: str
    idempotency_table: str

    # --- Optional Variables with Defaults ---
    idempotency_ttl_days: int
    max_bundle_input_mb: int
    log_level: str

    # --- Derived Properties ---
    @property
    def idempotency_ttl_seconds(self) -> int:
        return self.idempotency_ttl_days * 86_400

    @property
    def max_bundle_input_bytes(self) -> int:
        return self.max_bundle_input_mb * 1_048_576

    @classmethod
    def load_from_env(cls) -> "AppConfig":
        """
        Loads configuration from environment variables, performing validation and type casting.
        Fails fast with a ConfigurationError if anything is invalid.
        """
        try:
            # --- Handle required string variables ---
            distribution_bucket = os.environ["DISTRIBUTION_BUCKET_NAME"]
            service_name = os.environ["SERVICE_NAME"]
            environment = os.environ["ENVIRONMENT"]
            idempotency_table = os.environ["IDEMPOTENCY_TABLE_NAME"]

            # --- Handle optional and numeric variables with validation ---
            idempotency_ttl_days = int(os.getenv("IDEMPOTENCY_TTL_DAYS", "7"))
            if idempotency_ttl_days <= 0:
                raise ValueError("IDEMPOTENCY_TTL_DAYS must be a positive integer.")

            max_bundle_input_mb = int(os.getenv("MAX_BUNDLE_INPUT_MB", "100"))
            if max_bundle_input_mb <= 0:
                raise ValueError("MAX_BUNDLE_INPUT_MB must be a positive integer.")

            # --- Handle special-case variables like log level ---
            log_level = os.getenv("LOG_LEVEL", "INFO").upper()
            allowed_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if log_level not in allowed_log_levels:
                raise ValueError(
                    f"LOG_LEVEL must be one of {allowed_log_levels}, not '{log_level}'"
                )

        except KeyError as e:
            raise ConfigurationError(
                f"Missing required environment variable: {e.args[0]}"
            ) from e
        except (ValueError, TypeError) as e:
            raise ConfigurationError(
                f"Invalid value for an environment variable: {e}"
            ) from e

        return cls(
            distribution_bucket=distribution_bucket,
            service_name=service_name,
            environment=environment,
            idempotency_table=idempotency_table,
            idempotency_ttl_days=idempotency_ttl_days,
            max_bundle_input_mb=max_bundle_input_mb,
            log_level=log_level,
        )


# --- Singleton Factory Function (Lazy-loaded and Cached) ---
@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """
    Loads the application configuration from environment variables.
    The result is cached using lru_cache, so the environment is only read once
    on the first call. This avoids import-time side effects.
    """
    logger.info("Loading application configuration from environment...")
    return AppConfig.load_from_env()

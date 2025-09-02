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
    spool_file_max_size_mb: int
    timeout_guard_threshold_seconds: int
    max_bundle_on_disk_mb: int

    # --- Error Handling Configuration ---
    max_retries_per_record: int
    s3_operation_timeout_seconds: int
    error_sampling_rate: float
    enable_detailed_error_context: bool
    max_error_context_size_kb: int

    # --- Derived Properties ---
    @property
    def idempotency_ttl_seconds(self) -> int:
        return self.idempotency_ttl_days * 86_400

    @property
    def max_bundle_input_bytes(self) -> int:
        return self.max_bundle_input_mb * 1_048_576

    @property
    def spool_file_max_size_bytes(self) -> int:
        return self.spool_file_max_size_mb * 1_048_576

    @property
    def timeout_guard_threshold_ms(self) -> int:
        return self.timeout_guard_threshold_seconds * 1000

    @property
    def max_bundle_on_disk_bytes(self) -> int:
        return self.max_bundle_on_disk_mb * 1_048_576

    @property
    def max_error_context_size_bytes(self) -> int:
        return self.max_error_context_size_kb * 1024

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

            spool_file_max_size_mb = int(os.getenv("SPOOL_FILE_MAX_SIZE_MB", "64"))
            if spool_file_max_size_mb <= 0:
                raise ValueError("SPOOL_FILE_MAX_SIZE_MB must be a positive integer.")

            timeout_guard_threshold_seconds = int(
                os.getenv("TIMEOUT_GUARD_THRESHOLD_SECONDS", "10")
            )
            if timeout_guard_threshold_seconds <= 0:
                raise ValueError(
                    "TIMEOUT_GUARD_THRESHOLD_SECONDS must be a positive integer."
                )

            max_bundle_on_disk_mb = int(os.getenv("MAX_BUNDLE_ON_DISK_MB", "400"))
            if max_bundle_on_disk_mb <= 0:
                raise ValueError("MAX_BUNDLE_ON_DISK_MB must be a positive integer.")

            # --- Handle special-case variables like log level ---
            log_level = os.getenv("LOG_LEVEL", "INFO").upper()
            allowed_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if log_level not in allowed_log_levels:
                raise ValueError(
                    f"LOG_LEVEL must be one of {allowed_log_levels}, not '{log_level}'"
                )

            # --- Handle error handling configuration ---
            max_retries_per_record = int(os.getenv("MAX_RETRIES_PER_RECORD", "3"))
            if max_retries_per_record < 0:
                raise ValueError(
                    "MAX_RETRIES_PER_RECORD must be a non-negative integer."
                )

            s3_operation_timeout_seconds = int(
                os.getenv("S3_OPERATION_TIMEOUT_SECONDS", "30")
            )
            if s3_operation_timeout_seconds <= 0:
                raise ValueError(
                    "S3_OPERATION_TIMEOUT_SECONDS must be a positive integer."
                )

            error_sampling_rate = float(os.getenv("ERROR_SAMPLING_RATE", "1.0"))
            if not 0.0 <= error_sampling_rate <= 1.0:
                raise ValueError("ERROR_SAMPLING_RATE must be between 0.0 and 1.0.")

            enable_detailed_error_context = os.getenv(
                "ENABLE_DETAILED_ERROR_CONTEXT", "true"
            ).lower() in ("true", "1", "yes", "on")

            max_error_context_size_kb = int(
                os.getenv("MAX_ERROR_CONTEXT_SIZE_KB", "16")
            )
            if max_error_context_size_kb <= 0:
                raise ValueError(
                    "MAX_ERROR_CONTEXT_SIZE_KB must be a positive integer."
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
            spool_file_max_size_mb=spool_file_max_size_mb,
            timeout_guard_threshold_seconds=timeout_guard_threshold_seconds,
            max_bundle_on_disk_mb=max_bundle_on_disk_mb,
            max_retries_per_record=max_retries_per_record,
            s3_operation_timeout_seconds=s3_operation_timeout_seconds,
            error_sampling_rate=error_sampling_rate,
            enable_detailed_error_context=enable_detailed_error_context,
            max_error_context_size_kb=max_error_context_size_kb,
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

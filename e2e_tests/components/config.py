# e2e_tests/components/config.py

import argparse
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Config:
    """Configuration for the E2E test runner."""

    landing_bucket: str
    distribution_bucket: str
    description: str = "E2E Test Run"
    generator_type: str = "random"  # 'random' or 'compressible'
    test_type: str = "s3_trigger"  # 's3_trigger', 'direct_invoke', or 'idempotency_check'
    lambda_function_name: Optional[str] = None
    num_files: int = 10
    size_mb: int = 1
    concurrency: int = 8
    keep_files: bool = False
    timeout_seconds: int = 300
    report_file: Optional[str] = None
    verbose: bool = False
    raw_config: Dict[str, Any] = field(default_factory=dict, repr=False)


def load_configuration(args: argparse.Namespace) -> Config:
    """Loads configuration from file and overrides with CLI arguments."""
    config_data = {}
    if args.config:
        with open(args.config) as f:
            config_data = json.load(f)

    description = config_data.pop("description", "E2E Test Run")
    cli_args = {
        key: value
        for key, value in vars(args).items()
        if value is not None and key != "config"
    }
    config_data.update(cli_args)
    raw_config = config_data.copy()
    config_data["description"] = description

    if "landing_bucket" not in config_data or "distribution_bucket" not in config_data:
        raise ValueError("The --landing-bucket and --distribution-bucket are required.")

    return Config(raw_config=raw_config, **config_data)

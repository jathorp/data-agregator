# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Core Architectural Principles

- **Lambda-First Design**: The Python Lambda function is the core component; Terraform infrastructure serves as developer scaffolding that may evolve
- **Cost Efficiency**: All design decisions prioritize AWS cost optimization (ARM64 Graviton2, memory limits, timeout management)
- **Code Modularity**: Components are designed for future sharing across multiple Lambda functions

## Essential Commands

```bash
# Build Lambda package for deployment
./build.sh  # Creates dist/lambda.zip for ARM64 architecture

# Run unit tests (environment variables auto-loaded from pyproject.toml)
uv run pytest tests/unit/

# Run E2E tests (must be run from e2e_tests/ directory)
cd e2e_tests && python main.py --config configs/config_00_singe_file.json

# Install dependencies
uv sync

# Code quality checks
uv run ruff check src/ tests/
uv run mypy src/data_aggregator/
```

## Project Architecture

- **Dual Schema Pattern**: [`src/data_aggregator/schemas.py`](src/data_aggregator/schemas.py) uses TypedDict for static analysis and Pydantic for runtime validation with automatic S3 key sanitization
- **Memory Management**: [`src/data_aggregator/core.py`](src/data_aggregator/core.py) uses SpooledTemporaryFile to handle Lambda's 512MB memory limit efficiently
- **Idempotency**: [`src/data_aggregator/app.py:91`](src/data_aggregator/app.py:91) generates collision-proof keys using S3 object metadata
- **Graceful Processing**: Core bundling monitors Lambda timeout and stops processing new files when time is low

## Testing Requirements

- **E2E Test Directory**: E2E tests must be run from the `e2e_tests/` directory, not project root
- **Test Isolation**: Different S3 prefixes prevent conflicts (`direct-invoke-tests/` vs `data/`)
- **Direct Lambda Testing**: Use `{"e2e_test_direct_invoke": True}` to bypass SQS for testing
- **Environment Variables**: Unit tests require specific env vars defined in `pyproject.toml`

## Important Conventions

- **SQS Batch Failures**: Return `{"batchItemFailures": [{"itemIdentifier": "msg_id"}]}` for proper retry handling
- **S3 Key Handling**: Original keys preserved in `original_key` property after sanitization
- **Error Context**: All exceptions include structured context via `to_dict()` method for safe logging
- **ARM64 Deployment**: Lambda package must be built for ARM64 architecture
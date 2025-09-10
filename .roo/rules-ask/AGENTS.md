# Project Structure and Documentation Guide

## Project Organization

```
src/data_aggregator/  # AWS Lambda function code
e2e_tests/           # End-to-end test suite (run from this directory)
infra/               # Terraform infrastructure components
tests/unit/          # Unit tests with mocked AWS services
tests/integration/   # Integration tests using moto
```

## Key Architecture Files

- [`src/data_aggregator/app.py`](src/data_aggregator/app.py) - Lambda handler and SQS batch processing
- [`src/data_aggregator/core.py`](src/data_aggregator/core.py) - Core bundling logic with memory management
- [`src/data_aggregator/schemas.py`](src/data_aggregator/schemas.py) - Dual schema pattern (TypedDict + Pydantic)
- [`src/data_aggregator/exceptions.py`](src/data_aggregator/exceptions.py) - Structured exception hierarchy
- [`src/data_aggregator/config.py`](src/data_aggregator/config.py) - Environment variable configuration

## Testing Framework Structure

```bash
# Unit tests: Fast, isolated, mocked dependencies
uv run pytest tests/unit/

# Integration tests: AWS service integration with moto
uv run pytest tests/integration/

# E2E tests: Full pipeline with real AWS resources
cd e2e_tests && python main.py --config configs/config_XX_name.json
```

## Configuration Patterns

```python
# Environment variables loaded via AppConfig.load_from_env()
# Test environment variables defined in pyproject.toml [tool.pytest.ini_options]
# E2E test configurations in e2e_tests/configs/ directory
```

## Infrastructure Components

```
infra/components/01-network/         # VPC, subnets, security groups
infra/components/02-stateful-resources/  # S3, DynamoDB, SQS
infra/components/03-application/         # Lambda function, IAM
infra/components/04-observability/       # CloudWatch, alarms
```

## Development Workflow

1. Install dependencies: `uv sync`
2. Run unit tests: `uv run pytest tests/unit/`
3. Build Lambda package: `./build.sh`
4. Deploy infrastructure: `cd infra/components/XX && ./tf.sh dev apply`
5. Run E2E tests: `cd e2e_tests && python main.py --config configs/config_00_singe_file.json`
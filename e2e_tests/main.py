#!/usr/bin/env python

# e2e_tests/main.py

import argparse

import boto3
from botocore.exceptions import NoCredentialsError, NoRegionError, ClientError
from rich.console import Console
from rich.panel import Panel

from components.config import load_configuration, Config
from components.runner import E2ETestRunner


def verify_aws_connectivity(config: Config):
    """
    Performs pre-flight checks before the test runner is even instantiated.
    - Initializes AWS clients.
    - Verifies credentials and region are configured.
    - Verifies access to required S3 buckets and Lambda functions.
    - Exits gracefully with a clear error message on failure.
    """
    console = Console()
    console.print("\n--- [bold blue]Pre-flight Checks[/bold blue] ---")

    try:
        # 1. Create a session using the provided config. This is where
        #    NoCredentialsError or NoRegionError will most likely occur.
        session_args = {}

        session = boto3.Session(**session_args)
        s3_client = session.client("s3")
        console.log("[green]✓[/green] Boto3 S3 session initialized successfully.")

        # 2. Check S3 bucket access.
        s3_client.head_bucket(Bucket=config.landing_bucket)
        console.log(
            f"[green]✓[/green] Access confirmed for S3 bucket: '{config.landing_bucket}'"
        )
        s3_client.head_bucket(Bucket=config.distribution_bucket)
        console.log(
            f"[green]✓[/green] Access confirmed for S3 bucket: '{config.distribution_bucket}'"
        )

        # 3. If it's a test type that needs Lambda, check Lambda access.
        if config.test_type in ["direct_invoke", "idempotency_check"]:
            if not config.lambda_function_name:
                # This is a config validation error, not an AWS error.
                raise ValueError(
                    "'lambda_function_name' is required for this test type."
                )

            lambda_client = session.client("lambda")
            lambda_client.get_function_configuration(
                FunctionName=config.lambda_function_name
            )
            console.log(
                f"[green]✓[/green] Access confirmed for Lambda function: '{config.lambda_function_name}'"
            )

        console.print("[bold green]✅ Pre-flight checks passed.[/bold green]")

    except NoCredentialsError:
        console.print("\n[bold red]❌ PRE-FLIGHT CHECK FAILED[/bold red]\n")
        error_message = (
            "AWS credentials not found. Please configure them using one of the following methods:\n"
            "  1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
            "  2. A shared credentials file (~/.aws/credentials) with a profile.\n"
            "  3. An IAM role attached to the EC2 instance or ECS task."
        )
        console.print(
            Panel(error_message, title="Authentication Error", border_style="red")
        )
        exit(2)

    except NoRegionError:
        console.print("\n[bold red]❌ PRE-FLIGHT CHECK FAILED[/bold red]\n")
        error_message = (
            "An AWS region was not specified. Please configure it using one of the following methods:\n"
            "  1. The --aws-region command-line flag.\n"
            "  2. The 'aws_region' key in your JSON config file.\n"
            "  3. The AWS_REGION or AWS_DEFAULT_REGION environment variables.\n"
            "  4. The 'region' setting in your ~/.aws/config file."
        )
        console.print(
            Panel(error_message, title="Configuration Error", border_style="red")
        )
        exit(2)

    except ClientError as e:
        console.print("\n[bold red]❌ PRE-FLIGHT CHECK FAILED[/bold red]\n")
        error_code = e.response["Error"]["Code"]
        if error_code == "404":
            error_message = f"An S3 bucket specified in your config does not exist. Please verify bucket names."
        elif error_code == "403":
            error_message = f"Access Denied when trying to access an AWS resource. Please check your IAM permissions."
        elif error_code == "ResourceNotFoundException":
            error_message = f"Lambda function not found: '{config.lambda_function_name}'. Please check the function name."
        else:
            error_message = f"An unexpected AWS API error occurred: {e}"

        console.print(Panel(error_message, title="AWS API Error", border_style="red"))
        exit(2)

    except ValueError as e:
        # Catches our internal config validation errors
        console.print("\n[bold red]❌ PRE-FLIGHT CHECK FAILED[/bold red]\n")
        console.print(Panel(str(e), title="Configuration Error", border_style="red"))
        exit(2)


def main():
    """Main entry point for the test runner script."""
    parser = argparse.ArgumentParser(
        description="End-to-end test system for a data aggregator pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-c", "--config", help="Path to a JSON configuration file.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output, including full exception tracebacks.",
    )

    args = parser.parse_args()

    # 1. Load the configuration object first.
    config = load_configuration(args)

    # 2. Run the pre-flight check. This function will exit the script on failure.
    verify_aws_connectivity(config)

    # 3. If the check passes, we can safely create and run the E2ETestRunner.
    try:
        runner = E2ETestRunner(config)
        exit_code = runner.run()
        exit(exit_code)
    except Exception as e:
        # This is now a catch-all for unexpected *runtime* errors, not setup errors.
        print(f"\nAn unexpected error occurred during the test run: {e}")
        if config.verbose:
            import traceback
            traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

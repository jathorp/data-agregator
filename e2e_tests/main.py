#!/usr/bin/env python

# e2e_tests/main.py

import argparse

from components.config import load_configuration
from components.runner import E2ETestRunner


def main():
    """Main entry point for the test runner script."""
    parser = argparse.ArgumentParser(
        description="End-to-end test system for a data aggregator pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-c", "--config", help="Path to a JSON configuration file.")
    parser.add_argument(
        "--landing-bucket", help="S3 bucket for uploading source files."
    )
    parser.add_argument("--distribution-bucket", help="S3 bucket for final bundles.")
    parser.add_argument(
        "--num-files", type=int, help="Number of source files to generate."
    )
    parser.add_argument("--size-mb", type=int, help="Size of each source file in MB.")
    parser.add_argument("--concurrency", type=int, help="Number of parallel workers.")
    parser.add_argument(
        "--timeout-seconds", type=int, help="Timeout for the consumer phase."
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Do not delete local files on completion.",
    )
    parser.add_argument("--report-file", help="Path to save a JUnit XML test report.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output, including full exception tracebacks.",
    )

    args = parser.parse_args()

    try:
        config = load_configuration(args)
        runner = E2ETestRunner(config)
        exit_code = runner.run()
        exit(exit_code)
    except (ValueError, FileNotFoundError) as e:
        print(f"Configuration Error: {e}")
        exit(2)
    except Exception as e:
        # Catch-all for any other unexpected startup errors
        print(f"An unexpected error occurred: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        exit(3)


if __name__ == "__main__":
    main()

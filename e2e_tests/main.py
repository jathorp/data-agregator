#!/usr/bin/env python

# e2e_tests/main.py

import argparse

from components.config import load_configuration
from components.runner import E2ETestRunner
from components.pre_flight import verify_aws_connectivity


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

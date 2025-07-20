#!/usr/bin/env python

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TypedDict

import boto3
import botocore
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# --- Constants ---
MANIFEST_FILENAME = "manifest.json"
CHUNK_SIZE = 1024 * 1024  # 1 MiB


# --- Data Structures ---


class SourceFile(TypedDict):
    key: str
    size: int
    sha256: str


class TestManifest(TypedDict):
    run_id: str
    start_time: str
    config: Dict[str, Any]
    source_files: List[SourceFile]


class ValidationResult(TypedDict):
    key: str
    status: str  # 'PASS' or 'FAIL'
    details: str


@dataclass
class Config:
    """Configuration for the E2E test runner."""

    landing_bucket: str
    distribution_bucket: str
    num_files: int = 10
    size_mb: int = 1
    concurrency: int = 8
    keep_files: bool = False
    timeout_seconds: int = 300
    report_file: Optional[str] = None
    # A field to store the original CLI/file config for the manifest
    raw_config: Dict[str, Any] = field(default_factory=dict, repr=False)
    verbose: bool = False


# --- Main Test System Class ---


class E2ETestRunner:
    """Orchestrates the end-to-end test of a data aggregator pipeline."""

    def __init__(self, config: Config):
        self.config = config
        self.s3 = boto3.client("s3")
        self.console = Console()

        self.run_id = f"e2e-test-{uuid.uuid4().hex[:8]}"
        self.s3_prefix = self.run_id
        self.local_workspace = Path(tempfile.mkdtemp(prefix=f"{self.run_id}-"))
        self.source_dir = self.local_workspace / "source"
        self.extracted_dir = self.local_workspace / "extracted"

        self.source_dir.mkdir()
        self.extracted_dir.mkdir()

        # State tracking
        self.processed_bundle_keys: Set[str] = set()

    def _hash_file_in_chunks(self, path: Path) -> str:
        """
        Calculates the SHA256 hash of a file by reading it in chunks.
        This is memory-efficient for large files.
        """
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _generate_file_and_hash(self, path: Path) -> str:
        """Creates a local file of a given size and returns its SHA256 hash."""
        hasher = hashlib.sha256()
        with open(path, "wb") as f:
            for _ in range(self.config.size_mb):
                chunk = os.urandom(CHUNK_SIZE)
                f.write(chunk)
                hasher.update(chunk)
        return hasher.hexdigest()

    def _produce_one_file(self, index: int) -> SourceFile:
        """Worker function to generate, hash, and upload a single source file."""
        filename = f"source_file_{index + 1:04d}.bin"
        local_path = self.source_dir / filename
        s3_key = f"{self.s3_prefix}/{filename}"

        file_hash = self._generate_file_and_hash(local_path)
        self.s3.upload_file(str(local_path), self.config.landing_bucket, s3_key)

        return {
            "key": s3_key,
            "size": local_path.stat().st_size,
            "sha256": file_hash,
        }

    def _produce_and_upload(self) -> TestManifest:
        """Generates and uploads source files in parallel, creating a manifest."""
        self.console.print("\n--- [bold green]Producer Phase[/bold green] ---")
        manifest: TestManifest = {
            "run_id": self.run_id,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": self.config.raw_config,
            "source_files": [],
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Producing {self.config.num_files} source files...",
                total=self.config.num_files,
            )
            with ThreadPoolExecutor(max_workers=self.config.concurrency) as executor:
                futures = {
                    executor.submit(self._produce_one_file, i): i
                    for i in range(self.config.num_files)
                }
                for future in as_completed(futures):
                    manifest["source_files"].append(future.result())
                    progress.update(task, advance=1)

        # Sort files by key for deterministic manifest
        manifest["source_files"].sort(key=lambda x: x["key"])

        with open(self.local_workspace / MANIFEST_FILENAME, "w") as f:
            json.dump(manifest, f, indent=2)
        return manifest

    # This is the updated method within the E2ETestRunner class.

    def _consume_and_download(self, manifest: TestManifest):
        """
        Polls the distribution bucket, downloading and extracting bundles.
        This method is designed to be resilient to corrupted or incomplete files.
        """
        self.console.print("\n--- [bold yellow]Consumer Phase[/bold yellow] ---")
        expected_keys = {item["key"] for item in manifest["source_files"]}
        end_time = time.time() + self.config.timeout_seconds

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            timeout_task = progress.add_task(
                f"[yellow]Polling for bundles (timeout in {self.config.timeout_seconds}s)",
                total=self.config.timeout_seconds,
            )

            while time.time() < end_time:
                # Check for completion first
                extracted_files = {
                    f"{self.s3_prefix}/{p.name}"
                    for p in self.extracted_dir.glob("*")
                    if p.is_file()
                }
                if expected_keys.issubset(extracted_files):
                    progress.update(
                        timeout_task,
                        completed=self.config.timeout_seconds,
                        description="[green]All expected files found!",
                    )
                    return

                response = self.s3.list_objects_v2(
                    Bucket=self.config.distribution_bucket, Prefix="bundle-"
                )
                new_bundles = [
                    obj
                    for obj in response.get("Contents", [])
                    if obj["Key"] not in self.processed_bundle_keys
                ]

                for bundle_obj in new_bundles:
                    bundle_key = bundle_obj["Key"]
                    progress.log(f"Processing bundle: [magenta]{bundle_key}[/magenta]")
                    local_bundle_path = self.local_workspace / Path(bundle_key).name

                    # --- GRACEFUL ERROR HANDLING ---
                    # We wrap the download and extraction in a try block to handle
                    # issues like network errors or corrupted files without crashing.
                    try:
                        self.s3.download_file(
                            self.config.distribution_bucket,
                            bundle_key,
                            str(local_bundle_path),
                        )
                        self.processed_bundle_keys.add(bundle_key)

                        with tarfile.open(local_bundle_path, "r:gz") as tar:
                            tar.extractall(path=self.extracted_dir)
                        progress.log(
                            f"  [green]✓[/green] Successfully extracted [magenta]{bundle_key}[/magenta]."
                        )

                    except tarfile.ReadError as e:
                        # This catches the exact error you saw.
                        progress.log(
                            f"  [bold red]✗ ERROR:[/] Failed to read bundle [magenta]{bundle_key}[/]. "
                            f"The file is likely corrupt or incomplete. (Details: {e})"
                        )
                    except Exception as e:
                        # Catch any other unexpected errors during download/extraction.
                        progress.log(
                            f"  [bold red]✗ ERROR:[/] An unexpected error occurred with bundle [magenta]{bundle_key}[/]. "
                            f"(Details: {e})"
                        )

                progress.update(timeout_task, advance=2)
                time.sleep(2)

        # If the loop finishes without finding all files, it's a timeout.
        # We now check if any files were extracted at all.
        if not any(self.extracted_dir.iterdir()):
            self.console.print(
                "[bold red]Polling timed out. No valid bundles were downloaded and extracted.[/bold red]"
            )
        else:
            self.console.print(
                "[bold yellow]Polling timed out. Not all expected files were found in the downloaded bundles.[/bold yellow]"
            )

        # We no longer raise a TimeoutError here. Instead, we let the test proceed to the
        # validation phase, which will correctly report the missing files and fail the test.

        # Add this new method inside the E2ETestRunner class

    def _verify_aws_connectivity(self):
        """
        Performs pre-flight checks to ensure AWS credentials are set and buckets are accessible.
        Raises specific, user-friendly exceptions on failure.
        """
        self.console.print("\n--- [bold blue]Pre-flight Checks[/bold blue] ---")
        try:
            self.s3.head_bucket(Bucket=self.config.landing_bucket)
            self.console.log(
                f"[green]✓[/green] Access confirmed for landing bucket: '{self.config.landing_bucket}'"
            )

            self.s3.head_bucket(Bucket=self.config.distribution_bucket)
            self.console.log(
                f"[green]✓[/green] Access confirmed for distribution bucket: '{self.config.distribution_bucket}'"
            )

        except botocore.exceptions.NoCredentialsError:
            raise RuntimeError(
                "AWS credentials not found. Please configure them using one of the following methods:\n"
                "  1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
                "  2. A shared credentials file (~/.aws/credentials)\n"
                "  3. An IAM role attached to the EC2 instance or ECS task."
            ) from None  # <--- THIS IS THE KEY CHANGE

        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise RuntimeError(
                    f"A specified S3 bucket does not exist: {e.response['Error']['BucketName']}. "
                    "Please check your configuration."
                ) from None  # <--- AND HERE
            if e.response["Error"]["Code"] == "403":
                raise RuntimeError(
                    f"Access denied to S3 bucket: {e.response['Error']['BucketName']}. "
                    "Please check IAM permissions."
                ) from None  # <--- AND HERE
            raise RuntimeError(
                f"An AWS client error occurred: {e}"
            ) from None  # <--- AND HERE for the catch-all

    def _validate_one_file(
        self, source_record: SourceFile, extracted_path: Path
    ) -> ValidationResult:
        """Worker function to validate a single file's hash."""
        extracted_hash = self._hash_file_in_chunks(extracted_path)
        if extracted_hash == source_record["sha256"]:
            return {
                "key": source_record["key"],
                "status": "PASS",
                "details": "SHA-256 match",
            }
        else:
            return {
                "key": source_record["key"],
                "status": "FAIL",
                "details": f"Hash mismatch! Expected {source_record['sha256'][:10]}..., got {extracted_hash[:10]}...",
            }

    def _validate_results(self, manifest: TestManifest) -> List[ValidationResult]:
        """Compares manifest against extracted files in parallel, returning structured results."""
        self.console.print("\n--- [bold green]Validation Phase[/bold green] ---")
        source_map = {item["key"]: item for item in manifest["source_files"]}
        extracted_map = {
            f"{self.s3_prefix}/{p.name}": p
            for p in self.extracted_dir.glob("*")
            if p.is_file()
        }

        results: List[ValidationResult] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=self.console,
        ) as progress:
            validation_task = progress.add_task(
                "[cyan]Validating file integrity...", total=len(source_map)
            )
            with ThreadPoolExecutor(max_workers=self.config.concurrency) as executor:
                future_to_key = {
                    executor.submit(
                        self._validate_one_file, source_record, extracted_map[key]
                    ): key
                    for key, source_record in source_map.items()
                    if key in extracted_map
                }
                for future in as_completed(future_to_key):
                    results.append(future.result())
                    progress.update(validation_task, advance=1)

        # Check for missing files (those in source but not extracted)
        missing_keys = source_map.keys() - extracted_map.keys()
        for key in missing_keys:
            results.append(
                {
                    "key": key,
                    "status": "FAIL",
                    "details": "File not found in any output bundle.",
                }
            )

        # Check for extra files (those in extracted but not source)
        extra_keys = extracted_map.keys() - source_map.keys()
        for key in extra_keys:
            results.append(
                {
                    "key": key,
                    "status": "FAIL",
                    "details": "Extracted file was not in the original manifest.",
                }
            )

        return sorted(results, key=lambda x: x["key"])

    def _display_and_report(self, results: List[ValidationResult]):
        """Displays results to console and generates JUnit XML report if requested."""
        table = Table(title="Validation Results")
        table.add_column("S3 Key", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Details", style="yellow")

        for res in results:
            style = "green" if res["status"] == "PASS" else "red"
            table.add_row(
                res["key"], f"[{style}]{res['status']}[/{style}]", res["details"]
            )

        self.console.print(table)

        if self.config.report_file:
            self._generate_junit_report(results)
            self.console.print(
                f"JUnit XML report saved to: [bold blue]{self.config.report_file}[/bold blue]"
            )

    def _generate_junit_report(self, results: List[ValidationResult]):
        """Creates a JUnit XML file from the validation results."""
        failures = sum(1 for r in results if r["status"] == "FAIL")
        test_suite = ET.Element(
            "testsuite",
            name="DataAggregatorE2ETest",
            tests=str(len(results)),
            failures=str(failures),
        )
        for res in results:
            test_case = ET.SubElement(
                test_suite, "testcase", name=res["key"], classname="E2EFileValidation"
            )
            if res["status"] == "FAIL":
                failure = ET.SubElement(test_case, "failure", message=res["details"])
                failure.text = f"Key: {res['key']}\nDetails: {res['details']}"

        tree = ET.ElementTree(test_suite)
        ET.indent(tree, space="  ")
        tree.write(self.config.report_file, encoding="utf-8", xml_declaration=True)

    def _cleanup(self, manifest: Optional[TestManifest] = None):
        """Cleans up all resources: S3 source/distribution objects and local workspace."""
        self.console.print("\n--- [bold yellow]Cleanup Phase[/bold yellow] ---")

        # 1. Clean up source files from landing bucket
        if manifest and manifest.get("source_files"):
            keys_to_delete = [{"Key": obj["key"]} for obj in manifest["source_files"]]
            for i in range(0, len(keys_to_delete), 1000):
                chunk = keys_to_delete[i : i + 1000]
                self.s3.delete_objects(
                    Bucket=self.config.landing_bucket, Delete={"Objects": chunk}
                )
            self.console.log(
                f"Deleted {len(keys_to_delete)} source objects from '{self.config.landing_bucket}'."
            )

        # 2. Clean up processed bundles from distribution bucket
        if self.processed_bundle_keys:
            keys_to_delete = [{"Key": key} for key in self.processed_bundle_keys]
            for i in range(0, len(keys_to_delete), 1000):
                chunk = keys_to_delete[i : i + 1000]
                self.s3.delete_objects(
                    Bucket=self.config.distribution_bucket, Delete={"Objects": chunk}
                )
            self.console.log(
                f"Deleted {len(keys_to_delete)} bundle objects from '{self.config.distribution_bucket}'."
            )

        # 3. Clean up local workspace
        if self.config.keep_files:
            self.console.print(
                f"[yellow]Keeping local test files in: {self.local_workspace}[/yellow]"
            )
        else:
            shutil.rmtree(self.local_workspace)
            self.console.log("Cleaned up local workspace.")

    def run(self) -> int:
        """Executes the full test lifecycle."""
        manifest = None
        try:
            self.console.print(
                Panel(
                    f"Starting E2E Test Run\nRun ID: [bold blue]{self.run_id}[/bold blue]\nWorkspace: {self.local_workspace}",
                    title="Setup",
                    expand=False,
                )
            )

            self._verify_aws_connectivity()  # Call the new pre-flight check method

            manifest = self._produce_and_upload()
            self.console.print(
                "[green]✓ Producer finished.[/green] All source files uploaded."
            )

            self._consume_and_download(manifest)
            self.console.print(
                "[green]✓ Consumer finished.[/green] All bundles processed."
            )

            results = self._validate_results(manifest)
            self._display_and_report(results)

            return 0 if all(r["status"] == "PASS" for r in results) else 1

        except RuntimeError as e:
            self.console.print(f"\n[bold red]❌ TEST SETUP FAILED[/bold red]\n")
            self.console.print(
                Panel(str(e), title="Configuration Error", border_style="red")
            )
            # --- VERBOSE FLAG IN ACTION ---
            if self.config.verbose:
                self.console.print(
                    "\n[yellow]Verbose mode enabled. Full traceback:[/yellow]"
                )
                self.console.print_exception(show_locals=False)
            return 2

        except Exception as e:
            self.console.print(
                f"\n[bold red]An unexpected error occurred during the test run.[/bold red]"
            )
            # --- VERBOSE FLAG IN ACTION ---
            if self.config.verbose:
                self.console.print(
                    "\n[yellow]Verbose mode enabled. Full traceback:[/yellow]"
                )
                self.console.print_exception(show_locals=True)
            else:
                self.console.print(f"Error details: {e}")
                self.console.print(
                    "\n[dim]Run with the --verbose flag for a full traceback.[/dim]"
                )
            return 1

        finally:
            self._cleanup(manifest)


def load_configuration(args: argparse.Namespace) -> Config:
    """Loads configuration from file and overrides with CLI arguments."""
    config_data = {}
    if args.config:
        with open(args.config) as f:
            config_data = json.load(f)

    # Override file config with any provided CLI args
    cli_args = {
        key: value
        for key, value in vars(args).items()
        if value is not None and key != "config"
    }
    config_data.update(cli_args)

    # Store the final merged config for the manifest
    raw_config = config_data.copy()

    # Validate required fields
    if "landing_bucket" not in config_data or "distribution_bucket" not in config_data:
        raise ValueError(
            "The --landing-bucket and --distribution-bucket are required, "
            "either via CLI or config file."
        )

    return Config(raw_config=raw_config, **config_data)


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


if __name__ == "__main__":
    main()

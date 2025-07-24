# e2e_tests/components/runner.py
import base64
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
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, TypedDict, Any

import boto3
from botocore.client import Config as BotocoreConfig
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

from .config import Config
from .data_generator import (
    CompressibleTextGenerator,
    DataGenerator,
    RandomDataGenerator,
)


# --- Data Structures ---


class SourceFile(TypedDict):
    key: str
    size: int
    sha256: str


class TestManifest(TypedDict):
    run_id: str
    start_time: str
    config: dict[str, Any]
    source_files: List[SourceFile]


class ValidationResult(TypedDict):
    key: str
    status: str  # 'PASS' or 'FAIL'
    details: str


# --- Constants ---
MANIFEST_FILENAME = "manifest.json"
CHUNK_SIZE = 1024 * 1024  # 1 MiB

GENERATOR_MAP = {
    "random": RandomDataGenerator,
    "compressible": CompressibleTextGenerator,
}


class E2ETestRunner:
    """Orchestrates the end-to-end test of a data aggregator pipeline."""

    def __init__(self, config: Config):
        self.config = config

        # Create a custom botocore config with a longer timeout for the Lambda client.
        # The Lambda function itself can run for up to 15 minutes (900s), so we
        # need a client-side timeout that is slightly longer.
        self.lambda_client_config = BotocoreConfig(
            read_timeout=900, connect_timeout=10, retries={"max_attempts": 2}
        )

        # We only need this special config for the Lambda client. The S3 client is fine.
        self.lambda_client = boto3.client("lambda", config=self.lambda_client_config)

        self.s3 = boto3.client("s3")
        self.console = Console()
        self.manifest: Optional[TestManifest] = None

        self.run_id = f"e2e-test-{uuid.uuid4().hex[:8]}"

        # Set the S3 prefix based on the test type to isolate test data.
        if self.config.test_type in ["direct_invoke"]:
            # For direct invoke tests, use a prefix that SQS is NOT listening to.
            # This prevents a race condition with an SQS-triggered Lambda.
            base_prefix = "direct-invoke-tests"
        else:
            # For standard SQS-triggered tests, we MUST use the prefix that SQS
            # is configured to listen to (`data/`). This now includes idempotency_check.
            base_prefix = "data"

        self.s3_prefix = f"{base_prefix}/{self.run_id}"

        self.local_workspace = Path(tempfile.mkdtemp(prefix=f"{self.run_id}-"))
        self.source_dir = self.local_workspace / "source"
        self.extracted_dir = self.local_workspace / "extracted"

        self.source_dir.mkdir()
        self.extracted_dir.mkdir()
        self.processed_bundle_keys: Set[str] = set()

        # Instantiate the correct data generator based on config
        generator_class = GENERATOR_MAP.get(self.config.generator_type)
        if not generator_class:
            raise ValueError(f"Unknown generator_type: '{self.config.generator_type}'")
        self.data_generator: DataGenerator = generator_class()

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

    def _produce_one_file(self, index: int) -> SourceFile:
        """Worker function to generate, hash, and upload a single source file."""
        filename = f"source_file_{index + 1:04d}.bin"
        local_path = self.source_dir / filename
        s3_key = f"{self.s3_prefix}/{filename}"

        # Use the data generator strategy object
        file_hash = self.data_generator.generate(local_path, self.config.size_mb)

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

        self.manifest = manifest

        return self.manifest

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
                extracted_keys = {
                    str(p.relative_to(self.extracted_dir))
                    for p in self.extracted_dir.rglob("*")
                    if p.is_file()
                }
                if expected_keys.issubset(extracted_keys):
                    progress.update(
                        timeout_task,
                        completed=self.config.timeout_seconds,
                        description="[green]All expected files found!",
                    )
                    return  # This will now work and exit the loop immediately.

                response = self.s3.list_objects_v2(
                    Bucket=self.config.distribution_bucket
                )

                # Filter for new bundles based on the filename pattern
                new_bundles = [
                    obj
                    for obj in response.get("Contents", [])
                    if "bundle-" in obj["Key"]
                    and obj["Key"] not in self.processed_bundle_keys
                ]

                if not new_bundles:
                    # If no new bundles are found, just update the progress and sleep
                    progress.update(timeout_task, advance=2)
                    time.sleep(2)
                    continue

                for bundle_obj in new_bundles:
                    bundle_key = bundle_obj["Key"]
                    progress.log(f"Processing bundle: [magenta]{bundle_key}[/magenta]")
                    local_bundle_path = self.local_workspace / Path(bundle_key).name

                    try:
                        self.s3.download_file(
                            self.config.distribution_bucket,
                            bundle_key,
                            str(local_bundle_path),
                        )
                        self.processed_bundle_keys.add(bundle_key)

                        with tarfile.open(local_bundle_path, "r:gz") as tar:
                            tar.extractall(path=self.extracted_dir, filter="data")
                        progress.log(
                            f"  [green]✓[/green] Successfully extracted [magenta]{bundle_key}[/magenta]."
                        )

                    except tarfile.ReadError as e:
                        progress.log(
                            f"  [bold red]✗ ERROR:[/] Failed to read bundle [magenta]{bundle_key}[/]. "
                            f"The file is likely corrupt or incomplete. (Details: {e})"
                        )
                    except Exception as e:
                        progress.log(
                            f"  [bold red]✗ ERROR:[/] An unexpected error occurred with bundle [magenta]{bundle_key}[/]. "
                            f"(Details: {e})"
                        )

            # If the loop finishes, handle the timeout message
            if not any(self.extracted_dir.iterdir()):
                self.console.print(
                    "[bold red]Polling timed out. No valid bundles were downloaded and extracted.[/bold red]"
                )
            else:
                self.console.print(
                    "[bold yellow]Polling timed out. Not all expected files were found in the downloaded bundles.[/bold yellow]"
                )

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

        # --- THIS IS THE CORRECTED LOGIC ---
        # 1. Use rglob('*') to search recursively through all subdirectories.
        # 2. Use p.relative_to() to get the path as it was inside the tarball.
        extracted_map = {
            str(p.relative_to(self.extracted_dir)): p
            for p in self.extracted_dir.rglob("*")
            if p.is_file()
        }
        # The keys in extracted_map will now correctly be like:
        # 'e2e-test-6f7e65fb/source_file_0001.bin'

        results: List[ValidationResult] = []

        # The rest of the validation logic can now proceed without changes.
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

        # Check for missing files
        missing_keys = source_map.keys() - extracted_map.keys()
        for key in missing_keys:
            results.append(
                {
                    "key": key,
                    "status": "FAIL",
                    "details": "File not found in any output bundle.",
                }
            )

        # Check for extra files
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

    def _cleanup(self):
        """Cleans up all resources: S3 source/distribution objects and local workspace."""
        self.console.print("\n--- [bold yellow]Cleanup Phase[/bold yellow] ---")

        # 1. Clean up source files from landing bucket
        if self.manifest and self.manifest.get("source_files"):
            keys_to_delete = [
                {"Key": obj["key"]} for obj in self.manifest["source_files"]
            ]
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

    def _cleanup_stale_bundles(self, older_than_seconds: int = 240):
        """Deletes old test bundles from the distribution bucket to ensure a clean state."""
        self.console.print("\n--- [bold yellow]Pre-Test Cleanup[/bold yellow] ---")
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.config.distribution_bucket)

            stale_objects = []
            now = datetime.now(timezone.utc)

            for page in pages:
                for obj in page.get("Contents", []):
                    # Check if it looks like a bundle and is older than the threshold
                    if (
                        "bundle-" in obj["Key"]
                        and (now - obj["LastModified"]).total_seconds()
                        > older_than_seconds
                    ):
                        stale_objects.append({"Key": obj["Key"]})

            if not stale_objects:
                self.console.log(
                    "No stale bundles found in distribution bucket. Environment is clean."
                )
                return

            self.console.log(f"Found {len(stale_objects)} stale bundle(s) to delete...")
            # S3 delete_objects has a limit of 1000 keys per request
            for i in range(0, len(stale_objects), 1000):
                chunk = stale_objects[i : i + 1000]
                self.s3.delete_objects(
                    Bucket=self.config.distribution_bucket, Delete={"Objects": chunk}
                )
            self.console.log("[green]✓ Stale bundles cleaned up successfully.[/green]")

        except Exception as e:
            self.console.log(
                f"[bold red]Could not perform pre-test cleanup: {e}[/bold red]"
            )
            # We don't fail the test here, just log a warning.

    def run(self) -> int:
        """Executes the full test lifecycle."""
        try:
            self.console.print(
                Panel(
                    f"[cyan bold]{self.config.description}[/cyan bold]\n\n"
                    f"Run ID: [bold blue]{self.run_id}[/bold blue]\n"
                    f"Workspace: {self.local_workspace}",
                    title="Test Case",
                    expand=False,
                )
            )

            self._cleanup_stale_bundles()  # Try and revove any old test files

            if self.config.test_type == "direct_invoke":
                return self._run_direct_invoke_test()
            elif self.config.test_type == "idempotency_check":
                return self._run_idempotency_test()
            elif self.config.test_type == "key_sanitization":
                return self._run_key_sanitization_test()
            elif self.config.test_type == "file_not_found":
                return self._run_file_not_found_test()

            self.manifest = self._produce_and_upload()
            self.console.print(
                "[green]✓ Producer finished.[/green] All source files uploaded."
            )

            self._consume_and_download(self.manifest)
            self.console.print(
                "[green]✓ Consumer finished.[/green] All bundles processed."
            )

            results = self._validate_results(self.manifest)
            self._display_and_report(results)

            return 0 if all(r["status"] == "PASS" for r in results) else 1

        except RuntimeError as e:
            self.console.print("\n[bold red]❌ TEST SETUP FAILED[/bold red]\n")
            self.console.print(
                Panel(str(e), title="Configuration Error", border_style="red")
            )

            if self.config.verbose:
                self.console.print(
                    "\n[yellow]Verbose mode enabled. Full traceback:[/yellow]"
                )
                self.console.print_exception(show_locals=False)
            return 2

        except Exception as e:
            self.console.print(
                "\n[bold red]An unexpected error occurred during the test run.[/bold red]"
            )
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
            if self.manifest:
                self._cleanup()

    def _run_direct_invoke_test(self) -> int:
        """
        Runs a test by directly invoking the Lambda with a crafted payload.
        This is used for testing scenarios that require a guaranteed large batch.
        """
        self.console.print("\n--- [bold blue]Direct Invocation Test[/bold blue] ---")

        if not self.config.lambda_function_name:
            self.console.print(
                "[bold red]Configuration Error: 'lambda_function_name' must be set for a 'direct_invoke' test.[/bold red]"
            )
            return 2  # Setup failure code

        # 1. Produce files as normal
        manifest = self._produce_and_upload()
        self.console.print("[green]✓ Source files created.[/green]")

        # 2. Construct the S3EventRecord-like payload for the Lambda.
        lambda_payload_records = []
        for source_file in manifest["source_files"]:
            bucket_name = self.config.landing_bucket
            # This mimics the structure of a real S3 event notification.
            record = {
                "s3": {
                    "bucket": {
                        "name": bucket_name,
                        "arn": f"arn:aws:s3:::{bucket_name}",
                    },
                    "object": {"key": source_file["key"], "size": source_file["size"]},
                }
            }
            lambda_payload_records.append(record)

        payload = {"e2e_test_direct_invoke": True, "records": lambda_payload_records}

        # 3. Invoke the Lambda function directly.
        self.console.print(
            f"Directly invoking Lambda '{self.config.lambda_function_name}' with {len(payload['records'])} records."
        )

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.config.lambda_function_name,  # <-- CORRECTED
                InvocationType="RequestResponse",
                LogType="Tail",
                Payload=json.dumps(payload),
            )
        except Exception as e:
            self.console.print(f"[bold red]Lambda invocation failed: {e}[/bold red]")
            return 1

        # 4. Analyze the response and logs.
        log_result = base64.b64decode(response.get("LogResult", b"")).decode("utf-8")

        self.console.print("\n--- [bold yellow]Lambda Log Tail[/bold yellow] ---")
        self.console.print(Panel(log_result, border_style="yellow"))

        if response.get("FunctionError"):
            self.console.print(
                "[bold red]❌ TEST FAILED: Lambda function returned an error.[/bold red]"
            )
            return 1

        # 5. Check for the expected log message
        if "Predicted disk usage exceeds limit" in log_result:
            self.console.print(
                "\n[bold green]✅ TEST PASSED: Lambda correctly detected the disk limit and stopped processing.[/bold green]"
            )

            # Dynamically calculate how many files we EXPECT to have been processed.
            MAX_BUNDLE_ON_DISK_BYTES = 400 * 1024 * 1024
            file_size_bytes = self.config.size_mb * 1024 * 1024

            if file_size_bytes == 0:
                max_files_in_bundle = self.config.num_files
            else:
                max_files_in_bundle = MAX_BUNDLE_ON_DISK_BYTES // file_size_bytes

            # Create a new, smaller manifest containing only the files we expect to find.
            # The source_files in the manifest are already sorted by name.
            expected_manifest: TestManifest = {
                "run_id": manifest["run_id"],
                "start_time": manifest["start_time"],
                "config": manifest["config"],
                "source_files": manifest["source_files"][:max_files_in_bundle],
            }

            self.console.print(
                f"\nProceeding to validate the partial bundle. Expecting {len(expected_manifest['source_files'])} files."
            )

            # Now, run the consumer and validator against this *expected partial manifest*.
            self._consume_and_download(expected_manifest)
            results = self._validate_results(expected_manifest)
            self._display_and_report(results)

            # The test PASSES if all expected files passed validation.
            if all(r["status"] == "PASS" for r in results):
                self.console.print(
                    "[bold green]✅ Validation confirms the partial bundle is correct.[/bold green]"
                )
                return 0
            else:
                self.console.print(
                    "[bold red]❌ Validation of the partial bundle failed.[/bold red]"
                )
                return 1

        else:
            self.console.print(
                "[bold red]❌ TEST FAILED: The expected 'disk usage exceeds limit' log message was not found.[/bold red]"
            )
            return 1

    def _wait_for_bundle_and_get_key(self, timeout_seconds: int = 120) -> Optional[str]:
        """
        Polls the distribution bucket until a new bundle appears or a timeout is reached.
        Returns the S3 key of the first new bundle found.
        """
        self.console.print(f"[yellow]Polling for new bundle (timeout in {timeout_seconds}s)...[/yellow]")

        with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=self.console,
        ) as progress:
            polling_task = progress.add_task(
                "[yellow]Waiting...",
                total=timeout_seconds,
            )

            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                response = self.s3.list_objects_v2(Bucket=self.config.distribution_bucket)
                for obj in response.get("Contents", []):
                    # Find any object that looks like a bundle and that we haven't processed yet.
                    if "bundle-" in obj["Key"] and obj["Key"] not in self.processed_bundle_keys:
                        progress.update(polling_task, completed=timeout_seconds, description="[green]Found new bundle!")
                        self.console.log(f"[green]✓ Found new bundle:[/] [magenta]{obj['Key']}[/magenta]")
                        return obj["Key"]

                # Update progress and sleep
                progress.update(polling_task, advance=2)
                time.sleep(2)

        self.console.log("[yellow]Polling timed out. No new bundle was found.[/yellow]")
        return None

    def _run_idempotency_test(self) -> int:
        """
        Tests the versioning behavior by uploading a file, then overwriting it.
        It verifies that BOTH versions are processed, as each is a unique object.
        This validates the core business logic for handling updated data.
        """
        self.console.print("\n--- [bold blue]File Versioning Test (Scenario B)[/bold blue] ---")

        # --- Phase 1: Process Initial Version ---
        self.console.print("\n[cyan]Phase 1: Processing the initial file...[/cyan]")

        # 1. Produce a single source file. We need its local path for re-upload.
        filename = "idempotency_test_file_001.bin"
        local_path = self.source_dir / filename
        s3_key = f"{self.s3_prefix}/{filename}"
        file_hash = self.data_generator.generate(local_path, size_mb=1)
        self.s3.upload_file(str(local_path), self.config.landing_bucket, s3_key)
        self.console.log(f"Uploaded initial file to S3 key: [cyan]{s3_key}[/cyan]")

        # 2. We need a manifest to track what we uploaded.
        self.manifest = {
            "run_id": self.run_id,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": self.config.raw_config,
            "source_files": [{"key": s3_key, "size": local_path.stat().st_size, "sha256": file_hash}],
        }

        # 3. Wait for the first bundle to be created.
        bundle_key_1 = self._wait_for_bundle_and_get_key(timeout_seconds=120)
        if not bundle_key_1:
            self.console.print("[bold red]❌ TEST FAILED: Initial bundle was not created in time.[/bold red]")
            return 1
        self.processed_bundle_keys.add(bundle_key_1)  # Track this so cleanup works

        # 4. Validate the first bundle. This confirms the baseline test setup is working correctly.
        self._consume_and_download(self.manifest)
        results = self._validate_results(self.manifest)
        if not all(r["status"] == "PASS" for r in results):
            self.console.print("[bold red]❌ TEST FAILED: The initial bundle did not contain the correct file.[/bold red]")
            self._display_and_report(results)
            return 1
        self.console.log("[green]✓ Initial bundle created and validated successfully.[/green]")

        # --- Phase 2: Process Overwritten Version ---
        self.console.print("\n[cyan]Phase 2: Processing the overwritten file version...[/cyan]")

        # Re-upload the exact same file to the same key. This fires a new event for a new version.
        self.console.log(f"Re-uploading file to the same S3 key to create a new version...")
        self.s3.upload_file(str(local_path), self.config.landing_bucket, s3_key)

        # Wait to see if a *second* bundle is created. We EXPECT it to be.
        bundle_key_2 = self._wait_for_bundle_and_get_key(timeout_seconds=120)

        # --- Phase 3: Assertion ---
        self.console.print("\n[cyan]Phase 3: Verifying the outcome...[/cyan]")

        if bundle_key_2 and bundle_key_2 != bundle_key_1:
            self.console.print(
                "\n[bold green]✅ TEST PASSED: A new, distinct bundle was created for the new file version.[/bold green]")
            self.console.print("[bold green]   This confirms the system correctly processes updated files.[/bold green]")
            return 0
        else:
            self.console.print(
                f"\n[bold red]❌ TEST FAILED: A second bundle was not created for the new file version.[/bold red]")
            self.console.print(
                "[bold red]   This indicates a potential issue with the idempotency key or event processing.[/bold red]")
            return 1

    def _run_key_sanitization_test(self) -> int:
        """
        Tests the S3 key sanitization logic. Uploads a file with a path-traversal
        key and verifies that the Lambda's sanitization function correctly
        transforms it into a safe path before adding it to the bundle.
        """
        self.console.print("\n--- [bold blue]Key Sanitization Test (S3 Trigger)[/bold blue] ---")

        # 1. Define the keys as they will be uploaded to S3.
        input_safe_key = f"{self.s3_prefix}/safe_file.txt"
        input_malicious_key = f"{self.s3_prefix}/../../malicious_file.txt"

        # 2. IMPORTANT: Define the keys as we EXPECT them to be named *inside the bundle*
        #    after the Lambda's _sanitize_s3_key function runs.
        #    os.path.normpath('data/run-id/../../malicious.txt') -> 'malicious.txt'
        expected_output_safe_key = input_safe_key
        expected_output_malicious_key = os.path.normpath(input_malicious_key)

        # 3. Create and upload the files using the literal input keys.
        files_to_upload = {
            "safe": {"upload_key": input_safe_key, "local_name": "safe_file.txt"},
            "malicious": {"upload_key": input_malicious_key, "local_name": "malicious_file.txt"},
        }

        # Store hashes mapped to their EXPECTED output key
        hashes_by_expected_key = {}
        for file_type, file_info in files_to_upload.items():
            local_path = self.source_dir / file_info["local_name"]
            file_hash = self.data_generator.generate(local_path, size_mb=1)
            self.s3.upload_file(str(local_path), self.config.landing_bucket, file_info["upload_key"])
            self.console.log(f"Uploaded test file to S3 key: [cyan]{file_info['upload_key']}[/cyan]")

            if file_type == "safe":
                hashes_by_expected_key[expected_output_safe_key] = (local_path.stat().st_size, file_hash)
            else:
                hashes_by_expected_key[expected_output_malicious_key] = (local_path.stat().st_size, file_hash)

        # 4. Create the manifest with the keys we EXPECT to find in the bundle.
        manifest_records = [
            {"key": key, "size": size, "sha256": sha}
            for key, (size, sha) in hashes_by_expected_key.items()
        ]
        self.manifest = {
            "run_id": self.run_id,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": self.config.raw_config,
            "source_files": sorted(manifest_records, key=lambda x: x["key"]),
        }

        self.console.log(
            f"Manifest created. Expecting to find keys in bundle: {[r['key'] for r in self.manifest['source_files']]}")

        # 5. Run the standard consumer and validator.
        self._consume_and_download(self.manifest)
        results = self._validate_results(self.manifest)
        self._display_and_report(results)

        # 6. Success is now simple: ALL files in our corrected manifest must pass validation.
        if all(r["status"] == "PASS" for r in results):
            self.console.print(
                "\n[bold green]✅ TEST PASSED: The key was correctly sanitized and all files were processed.[/bold green]")
            return 0
        else:
            self.console.print("\n[bold red]❌ TEST FAILED: Validation failed against the sanitized keys.[/bold red]")
            return 1


    def _run_file_not_found_test(self) -> int:
        """
        Tests resilience when an S3 object is deleted before processing. It uploads
        a batch of files, deletes one, and expects the final bundle to contain
        only the remaining files.
        """
        self.console.print("\n--- [bold blue]File Not Found Resilience Test[/bold blue] ---")

        # 1. Use the standard producer to upload the initial batch of files.
        #    This gives us a manifest of all files that were created.
        initial_manifest = self._produce_and_upload()
        self.console.print(
            f"[green]✓ Producer finished.[/green] {len(initial_manifest['source_files'])} source files uploaded.")

        if not initial_manifest["source_files"]:
            self.console.print("[bold red]Error: No source files were produced for the test.[/bold red]")
            return 1

        # 2. Select one file to delete. Let's pick the last one for simplicity.
        file_to_delete = initial_manifest["source_files"][-1]
        self.console.log(f"Deleting one object to simulate race condition: [cyan]{file_to_delete['key']}[/cyan]")

        try:
            self.s3.delete_object(Bucket=self.config.landing_bucket, Key=file_to_delete['key'])
        except Exception as e:
            self.console.print(f"[bold red]Failed to delete object from S3: {e}[/bold red]")
            return 1

        # 3. CRITICAL: Create the final manifest that the validator will use.
        #    This manifest should ONLY contain the files we expect to find.
        expected_files = initial_manifest["source_files"][:-1]
        self.manifest = {
            "run_id": self.run_id,
            "start_time": initial_manifest["start_time"],
            "config": self.config.raw_config,
            "source_files": expected_files,
        }

        self.console.log(
            f"Manifest updated. Expecting to find {len(self.manifest['source_files'])} files in the final bundle.")

        # 4. Run the standard consumer and validator against the *expected* manifest.
        self._consume_and_download(self.manifest)
        results = self._validate_results(self.manifest)
        self._display_and_report(results)

        # 5. The success condition is that all *expected* files passed validation.
        if all(r["status"] == "PASS" for r in results):
            self.console.print(
                "\n[bold green]✅ TEST PASSED: The pipeline correctly skipped the deleted file and processed the rest.[/bold green]")
            return 0
        else:
            self.console.print(
                "\n[bold red]❌ TEST FAILED: Validation failed. The bundle did not contain the correct set of files.[/bold red]")
            return 1


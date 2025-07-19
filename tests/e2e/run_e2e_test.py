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
from pathlib import Path
from typing import Any, Dict, List, Set, TypedDict

import boto3
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table


# --- Data Structures for our Manifest & Validation ---


class SourceFile(TypedDict):
    key: str
    size: int
    sha256: str


class TestManifest(TypedDict):
    run_id: str
    start_time: str
    config: Dict
    source_files: List[SourceFile]


class ValidationResult(TypedDict):
    key: str
    status: str  # 'PASS' or 'FAIL'
    details: str


# --- Main Test System Class ---


class E2ETestRunner:
    """Orchestrates the end-to-end test of the data aggregator pipeline."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.landing_bucket = config["landing_bucket"]
        self.distribution_bucket = config["distribution_bucket"]
        self.num_files = config["num_files"]
        self.size_mb = config["size_mb"]
        self.concurrency = config["concurrency"]
        self.keep_files = config["keep_files"]
        self.report_file = config.get("report_file")

        self.s3 = boto3.client("s3")
        self.console = Console()

        self.run_id = str(uuid.uuid4())[:8]
        self.s3_prefix = f"e2e-test-{self.run_id}"
        self.local_workspace = Path(tempfile.mkdtemp(prefix=f"e2e-test-{self.run_id}-"))
        self.source_dir = self.local_workspace / "source"
        self.extracted_dir = self.local_workspace / "extracted"

        self.source_dir.mkdir()
        self.extracted_dir.mkdir()

    def _generate_file_and_hash(self, path: Path) -> str:
        """Creates a local file of a given size and returns its SHA256 hash."""
        hasher = hashlib.sha256()
        with open(path, "wb") as f:
            for _ in range(self.size_mb):
                chunk = os.urandom(1024 * 1024)
                f.write(chunk)
                hasher.update(chunk)
        return hasher.hexdigest()

    def _produce_one_file(self, index: int) -> SourceFile:
        """Worker function to generate, hash, and upload a single file."""
        filename = f"source_file_{index + 1:03d}.bin"
        local_path = self.source_dir / filename
        s3_key = f"{self.s3_prefix}/{filename}"

        file_hash = self._generate_file_and_hash(local_path)
        self.s3.upload_file(str(local_path), self.landing_bucket, s3_key)

        return {
            "key": s3_key,
            "size": local_path.stat().st_size,
            "sha256": file_hash,
        }

    def _produce_and_upload(self) -> TestManifest:
        """Generates and uploads files in parallel, creating a manifest."""
        manifest: TestManifest = {
            "run_id": self.run_id,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": self.config,
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
                f"[bold cyan]Producing {self.num_files} source file(s)...",
                total=self.num_files,
            )

            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = [
                    executor.submit(self._produce_one_file, i)
                    for i in range(self.num_files)
                ]
                for future in as_completed(futures):
                    manifest["source_files"].append(future.result())
                    progress.update(task, advance=1)

        with open(self.local_workspace / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
        return manifest

    def _consume_and_download(self):
        """Polls the distribution bucket, downloads, and extracts bundles."""
        found_files_count = 0
        processed_bundle_keys: Set[str] = set()
        timeout_seconds = 300
        start_time = time.time()

        with Live(console=self.console, refresh_per_second=4) as live:
            while found_files_count < self.num_files:
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(
                        "Polling for output bundles timed out after 5 minutes."
                    )

                response = self.s3.list_objects_v2(
                    Bucket=self.distribution_bucket, Prefix="bundle-"
                )
                bundles_to_process = [
                    obj
                    for obj in response.get("Contents", [])
                    if obj["Key"] not in processed_bundle_keys
                ]

                if not bundles_to_process:
                    live.update(
                        Panel(
                            f"[bold yellow]Polling for bundles... Found {found_files_count}/{self.num_files} source files.",
                            title="Consumer",
                        )
                    )
                    time.sleep(2)
                    continue

                for bundle_obj in bundles_to_process:
                    bundle_key = bundle_obj["Key"]
                    local_bundle_path = self.local_workspace / os.path.basename(
                        bundle_key
                    )

                    live.update(
                        f"Downloading bundle: [bold magenta]{bundle_key}[/bold magenta]"
                    )
                    self.s3.download_file(
                        self.distribution_bucket, bundle_key, str(local_bundle_path)
                    )
                    self.s3.delete_object(
                        Bucket=self.distribution_bucket, Key=bundle_key
                    )
                    processed_bundle_keys.add(bundle_key)

                    with tarfile.open(local_bundle_path, "r:gz") as tar:
                        tar.extractall(path=self.extracted_dir)

                    found_files_count = len(
                        [p for p in self.extracted_dir.glob("**/*") if p.is_file()]
                    )

    def _validate_results(self, manifest: TestManifest) -> List[ValidationResult]:
        """Compares manifest against extracted files, returning structured results."""
        self.console.print("\n--- [bold green]Validation Phase[/bold green] ---")

        source_files_map = {item["key"]: item for item in manifest["source_files"]}
        extracted_files = (p for p in self.extracted_dir.rglob("*") if p.is_file())
        extracted_map = {
            f"{self.s3_prefix}/{p.relative_to(self.extracted_dir)}": p
            for p in extracted_files
        }

        results: List[ValidationResult] = []

        # Check for missing and mismatched files
        for key, source_record in source_files_map.items():
            if key not in extracted_map:
                results.append(
                    {
                        "key": key,
                        "status": "FAIL",
                        "details": "File was not found in any output bundle.",
                    }
                )
                continue

            hasher = hashlib.sha256()
            with open(extracted_map[key], "rb") as f:
                hasher.update(f.read())
            extracted_hash = hasher.hexdigest()

            if extracted_hash == source_record["sha256"]:
                results.append(
                    {"key": key, "status": "PASS", "details": "SHA-256 match"}
                )
            else:
                results.append(
                    {
                        "key": key,
                        "status": "FAIL",
                        "details": f"Hash mismatch! Expected {source_record['sha256'][:10]}..., got {extracted_hash[:10]}...",
                    }
                )

        # Check for extra files that shouldn't exist
        for key in extracted_map:
            if key not in source_files_map:
                results.append(
                    {
                        "key": key,
                        "status": "FAIL",
                        "details": "Extracted file was not in the original manifest.",
                    }
                )

        return results

    def _display_and_report(self, results: List[ValidationResult]):
        """Displays results to console and generates JUnit XML report if requested."""
        table = Table(title="Validation Results")
        table.add_column("S3 Key", style="cyan", no_wrap=True)
        table.add_column("Status", style="white")
        table.add_column("Details", style="yellow")

        for res in results:
            style = "[green]" if res["status"] == "PASS" else "[red]"
            table.add_row(res["key"], f"{style}{res['status']}", res["details"])

        self.console.print(table)

        if self.report_file:
            self._generate_junit_report(results)
            self.console.print(
                f"JUnit XML report saved to: [bold blue]{self.report_file}[/bold blue]"
            )

    def _generate_junit_report(self, results: List[ValidationResult]):
        """Creates a JUnit XML file from the validation results."""
        failures = sum(1 for r in results if r["status"] == "FAIL")

        test_suite = ET.Element(
            "testsuite",
            name="DataAggregatorE2ETest",
            tests=str(len(results)),
            failures=str(failures),
            time="0",
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
        tree.write(self.report_file, encoding="utf-8", xml_declaration=True)

    def _cleanup_s3(self, manifest: TestManifest):
        """Cleans up source files from the landing bucket."""
        self.console.print("\n--- [bold yellow]S3 Cleanup Phase[/bold yellow] ---")
        keys_to_delete = [obj["key"] for obj in manifest.get("source_files", [])]
        if not keys_to_delete:
            return

        # S3 delete_objects has a limit of 1000 keys per request
        for i in range(0, len(keys_to_delete), 1000):
            chunk = keys_to_delete[i : i + 1000]
            delete_payload = {"Objects": [{"Key": key} for key in chunk]}
            self.s3.delete_objects(Bucket=self.landing_bucket, Delete=delete_payload)

        self.console.print(
            f"Deleted {len(keys_to_delete)} source object(s) from '{self.landing_bucket}'."
        )

    def run(self) -> int:
        """Executes the full test lifecycle."""
        manifest = {}
        try:
            self.console.print(
                Panel(
                    f"Starting E2E Test Run\nRun ID: [bold blue]{self.run_id}[/bold blue]\nWorkspace: {self.local_workspace}",
                    title="Setup",
                )
            )

            manifest = self._produce_and_upload()
            self.console.print(
                "[green]✓ Producer finished.[/green] All files uploaded."
            )

            self._consume_and_download()
            self.console.print(
                "[green]✓ Consumer finished.[/green] All bundles downloaded and extracted."
            )

            results = self._validate_results(manifest)
            self._display_and_report(results)

            if all(r["status"] == "PASS" for r in results):
                self.console.print("\n[bold green]✅ E2E TEST PASSED[/bold green]")
                return 0
            else:
                self.console.print("\n[bold red]❌ E2E TEST FAILED[/bold red]")
                return 1

        except Exception as e:
            self.console.print(f"\n[bold red]An error occurred: {e}[/bold red]")
            self.console.print_exception(show_locals=True)
            return 1
        finally:
            if manifest:
                self._cleanup_s3(manifest)
            if self.keep_files:
                self.console.print(
                    f"\n[yellow]Keeping local test files in: {self.local_workspace}[/yellow]"
                )
            else:
                shutil.rmtree(self.local_workspace)
                self.console.print("\n[dim]Cleaned up local workspace.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end test system for the Data Aggregator pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Configuration arguments
    parser.add_argument("-c", "--config", help="Path to a JSON configuration file.")

    # Individual arguments (override config file)
    parser.add_argument(
        "--landing-bucket", help="S3 bucket for uploading source files."
    )
    parser.add_argument(
        "--distribution-bucket", help="S3 bucket to poll for final bundles."
    )
    parser.add_argument(
        "--num-files", type=int, help="Number of source files to generate."
    )
    parser.add_argument(
        "--size-mb", type=int, help="Size of each source file in megabytes."
    )
    parser.add_argument("--concurrency", type=int, help="Number of parallel uploads.")
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Do not delete local test files after completion.",
    )
    parser.add_argument("--report-file", help="Path to save a JUnit XML test report.")

    args = parser.parse_args()

    # --- Configuration Loading Logic ---
    # Command-line args > Config file > Defaults

    config = {
        "num_files": 10,
        "size_mb": 1,
        "concurrency": 4,
        "keep_files": False,
    }

    if args.config:
        with open(args.config) as f:
            config.update(json.load(f))

    # Override with command-line arguments that were actually provided
    cli_args = {key: value for key, value in vars(args).items() if value is not None}
    config.update(cli_args)

    # Final validation
    if "landing_bucket" not in config or "distribution_bucket" not in config:
        parser.error(
            "The --landing-bucket and --distribution-bucket arguments are required, either via CLI or config file."
        )

    runner = E2ETestRunner(config)
    exit(runner.run())


if __name__ == "__main__":
    main()

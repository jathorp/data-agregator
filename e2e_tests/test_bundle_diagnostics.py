#!/usr/bin/env python3
"""
Test script to verify the enhanced bundle download and extraction diagnostics.
This simulates the bundle processing without requiring AWS credentials.
"""

import tarfile
import tempfile
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn

def create_test_bundle(bundle_path: Path, files_to_include: list):
    """Create a test tarball with specified files."""
    with tarfile.open(bundle_path, "w:gz") as tar:
        for i, file_info in enumerate(files_to_include):
            # Create a temporary file with the specified content
            temp_file = bundle_path.parent / f"temp_file_{i}.bin"
            temp_file.write_text(file_info['content'])
            
            # Add it to the tarball with the specified name
            tar.add(temp_file, arcname=file_info['name'])
            
            # Clean up temp file
            temp_file.unlink()

def test_bundle_processing():
    """Test the enhanced bundle processing logic."""
    console = Console()
    console.print("\n--- [bold cyan]Testing Enhanced Bundle Diagnostics[/bold cyan] ---")
    
    # Create a temporary workspace
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        extracted_dir = workspace / "extracted"
        extracted_dir.mkdir()
        
        # Test Case 1: Normal bundle with files
        console.print("\n[yellow]Test Case 1: Normal bundle with files[/yellow]")
        bundle_path = workspace / "test_bundle.tar.gz"
        
        test_files = [
            {"name": "data/e2e-test-12345/file1.bin", "content": "test content 1"},
            {"name": "data/e2e-test-12345/file2.bin", "content": "test content 2"},
        ]
        
        create_test_bundle(bundle_path, test_files)
        
        # Simulate the enhanced processing logic
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            bundle_key = "2025/09/03/12/bundle-test-12345.tar.gz"
            progress.log(f"Processing bundle: [magenta]{bundle_key}[/magenta]")
            
            # Verify download (simulated)
            if not bundle_path.exists():
                progress.log(f"  [bold red]✗ ERROR:[/] Downloaded file does not exist: {bundle_path}")
                return False
                
            file_size = bundle_path.stat().st_size
            progress.log(f"  [dim]Downloaded bundle size: {file_size} bytes[/dim]")
            
            if file_size == 0:
                progress.log(f"  [bold red]✗ ERROR:[/] Downloaded bundle is empty")
                return False
            
            # Enhanced tarball inspection
            progress.log(f"  [dim]Opening tarball for inspection...[/dim]")
            with tarfile.open(bundle_path, "r:gz") as tar:
                members = tar.getmembers()
                file_count = len(members)
                
                progress.log(f"  [dim]Found {file_count} file(s) in bundle:[/dim]")
                for member in members:
                    progress.log(f"    - [cyan]{member.name}[/cyan] ({member.size} bytes)")
                
                if file_count == 0:
                    progress.log(f"  [bold yellow]WARNING:[/] Bundle contains no files")
                    return False
                
                # Log extraction details
                progress.log(f"  [dim]Extracting to: {extracted_dir}[/dim]")
                
                # Extract with 'data' filter to match the actual implementation
                tar.extractall(path=extracted_dir, filter='data')
                
                # Verify extraction succeeded
                extracted_files = list(extracted_dir.rglob("*"))
                extracted_file_count = len([f for f in extracted_files if f.is_file()])
                progress.log(f"  [dim]Extraction complete. Found {extracted_file_count} files in extracted directory[/dim]")
                
            progress.log(f"  [green]✓[/green] Successfully processed [magenta]{bundle_key}[/magenta].")
        
        # Show extracted contents
        console.print("\n[cyan]Extracted files:[/cyan]")
        for item in sorted(extracted_dir.rglob("*")):
            if item.is_file():
                relative_path = item.relative_to(extracted_dir)
                size = item.stat().st_size
                console.print(f"  📄 [cyan]{relative_path}[/cyan] ({size} bytes)")
        
        # Test Case 2: Empty bundle
        console.print("\n[yellow]Test Case 2: Empty bundle[/yellow]")
        empty_bundle_path = workspace / "empty_bundle.tar.gz"
        create_test_bundle(empty_bundle_path, [])
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            bundle_key = "2025/09/03/12/empty-bundle-test.tar.gz"
            progress.log(f"Processing bundle: [magenta]{bundle_key}[/magenta]")
            
            file_size = empty_bundle_path.stat().st_size
            progress.log(f"  [dim]Downloaded bundle size: {file_size} bytes[/dim]")
            
            with tarfile.open(empty_bundle_path, "r:gz") as tar:
                members = tar.getmembers()
                file_count = len(members)
                
                progress.log(f"  [dim]Found {file_count} file(s) in bundle:[/dim]")
                
                if file_count == 0:
                    progress.log(f"  [bold yellow]WARNING:[/] Bundle contains no files")
                else:
                    for member in members:
                        progress.log(f"    - [cyan]{member.name}[/cyan] ({member.size} bytes)")
    
    console.print("\n[green]✓ Bundle diagnostics test completed successfully![/green]")
    return True

if __name__ == "__main__":
    test_bundle_processing()

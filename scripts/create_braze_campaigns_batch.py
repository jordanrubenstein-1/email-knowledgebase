#!/usr/bin/env python3
"""
Batch create multiple Braze email campaigns from a directory of YAML config files.

Usage:
    uv run python scripts/create_braze_campaigns_batch.py --dir campaigns/to-create/ --brand HAV
    uv run python scripts/create_braze_campaigns_batch.py --dir campaigns/to-create/ --workers 5 --dry-run
"""

import sys
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple
import threading

sys.path.insert(0, str(Path(__file__).parent))
from create_braze_campaign import create_campaign_workflow, load_config
from validate_campaign_config import validate_campaign_config

# Thread-safe counters
print_lock = threading.Lock()
results_lock = threading.Lock()


def process_campaign_file(config_path: Path, brand: str = None, dry_run: bool = False, schedule: bool = False) -> Tuple[str, bool, str]:
    """Process a single campaign config file.
    
    Args:
        config_path: Path to campaign config YAML
        brand: Optional brand override
        dry_run: If True, validate but don't create
        schedule: If True, schedule campaigns after creation (requires explicit permission)
    
    Returns:
        Tuple of (campaign_name, success, error_message)
    """
    try:
        config = load_config(config_path)
        campaign = config.get("campaign", {})
        campaign_name = campaign.get("name", config_path.name)
        
        # Quick validation
        is_valid, errors, _, warnings = validate_campaign_config(config)
        if not is_valid:
            error_msg = "; ".join(errors)
            if warnings:
                error_msg += " | Warnings: " + "; ".join(warnings)
            return campaign_name, False, error_msg
        
        # Create campaign (will NOT schedule unless --schedule flag is used)
        success = create_campaign_workflow(config_path, brand, dry_run, schedule)
        
        if success:
            return campaign_name, True, ""
        else:
            return campaign_name, False, "Campaign creation failed"
    
    except Exception as e:
        return config_path.name, False, str(e)


def process_batch(config_dir: Path, brand: str = None, dry_run: bool = False, 
                 workers: int = 3, schedule: bool = False) -> Dict[str, List[str]]:
    """Process all YAML files in a directory.
    
    Args:
        config_dir: Directory containing campaign config YAML files
        brand: Optional brand override
        dry_run: If True, validate but don't create
        workers: Number of parallel workers
        schedule: If True, schedule campaigns after creation (requires explicit permission)
    
    Returns:
        Dictionary with 'success' and 'failed' lists of campaign names
    """
    if not config_dir.exists():
        print(f"Error: Directory not found: {config_dir}")
        return {"success": [], "failed": []}
    
    # Find all YAML files
    config_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
    
    # Filter out template and example files
    config_files = [f for f in config_files 
                   if not f.name.startswith("_") and not f.name.startswith("example")]
    
    if not config_files:
        print(f"No campaign config files found in {config_dir}")
        return {"success": [], "failed": []}
    
    print(f"Found {len(config_files)} campaign config files")
    print(f"Processing with {workers} workers...")
    if dry_run:
        print("[DRY RUN MODE - No campaigns will be created]")
    elif schedule:
        print("⚠ WARNING: Campaigns will be SCHEDULED (will send emails)")
    else:
        print("✓ SAFE MODE: Campaigns will be created but NOT scheduled")
    print("="*60)
    
    results = {"success": [], "failed": []}
    completed = [0]
    total = len(config_files)
    
    def process_with_logging(config_path):
        """Process a config file and log results."""
        campaign_name, success, error = process_campaign_file(config_path, brand, dry_run, schedule)
        
        with results_lock:
            if success:
                results["success"].append(campaign_name)
            else:
                results["failed"].append((campaign_name, error))
            completed[0] += 1
        
        with print_lock:
            status = "✓" if success else "✗"
            print(f"[{completed[0]}/{total}] {status} {campaign_name}")
            if not success and error:
                print(f"    Error: {error}")
        
        return campaign_name, success, error
    
    # Process in parallel
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_with_logging, f): f for f in config_files}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                config_path = futures[future]
                with print_lock:
                    print(f"✗ {config_path.name}: Unexpected error: {e}")
                with results_lock:
                    results["failed"].append((config_path.name, str(e)))
    
    return results


def print_summary(results: Dict[str, List]):
    """Print summary of batch processing results."""
    print("\n" + "="*60)
    print("BATCH PROCESSING SUMMARY")
    print("="*60)
    
    success_count = len(results["success"])
    failed_count = len(results["failed"])
    total = success_count + failed_count
    
    print(f"Total campaigns: {total}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")
    
    if results["success"]:
        print(f"\n✓ Successful campaigns:")
        for name in results["success"]:
            print(f"  - {name}")
    
    if results["failed"]:
        print(f"\n✗ Failed campaigns:")
        for name, error in results["failed"]:
            print(f"  - {name}")
            print(f"    Error: {error}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch create Braze email campaigns from YAML config files"
    )
    parser.add_argument(
        "--dir",
        type=str,
        required=True,
        help="Directory containing campaign config YAML files"
    )
    parser.add_argument(
        "--brand",
        type=str,
        help="Brand code (overrides config if provided)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel workers (default: 3)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configurations without creating campaigns"
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Schedule campaigns after creation (requires explicit permission)"
    )
    
    args = parser.parse_args()
    
    # Safety check: warn if scheduling
    if args.schedule and not args.dry_run:
        print("⚠ WARNING: You are about to SCHEDULE campaigns that will send emails.")
        print("   This will send emails to the specified audiences at scheduled times.")
        response = input("   Type 'yes' to confirm scheduling: ")
        if response.lower() != 'yes':
            print("   Scheduling cancelled. Campaigns will be created but not scheduled.")
            args.schedule = False
    
    config_dir = Path(args.dir)
    if not config_dir.is_absolute():
        # Try relative to project root
        project_root = Path(__file__).parent.parent
        config_dir = project_root / config_dir
    
    try:
        results = process_batch(config_dir, args.brand, args.dry_run, args.workers, args.schedule)
        print_summary(results)
        
        # Exit with error code if any failed
        if results["failed"]:
            sys.exit(1)
        else:
            sys.exit(0)
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

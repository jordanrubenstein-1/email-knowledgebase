#!/usr/bin/env python3
"""
Backfill schedule_type for existing Braze campaign YAMLs by re-fetching /campaigns/details.

The Braze API returns schedule_type as a top-level field for already-sent campaigns:
  - time_based        — scheduled batch send (fixed UTC time, local-time, or intelligent timing;
                        Braze does NOT distinguish these sub-types for sent campaigns)
  - action_based      — triggered by user action (canvas action step)
  - api_triggered     — fired via Braze send API

NOTE: local_time_send and sto (STO/Intelligent Timing) are NOT available from the Braze
/campaigns/details endpoint for already-sent campaigns. The schedule object with
in_local_time/at_optimal_time is only returned for unsent campaigns. The heuristic
(first_sent/last_sent spread) is the only way to infer these for historical campaigns.

Skips braze_type=canvas/canvas_step and Klaviyo campaigns.
Writes each YAML immediately after fetch — safe to interrupt and re-run.

Usage:
    uv run python scripts/backfill_scheduling_metadata.py --brand ID
    uv run python scripts/backfill_scheduling_metadata.py --brand ID --limit 10 --dry-run
    uv run python scripts/backfill_scheduling_metadata.py  # all Braze brands
    uv run python scripts/backfill_scheduling_metadata.py --force  # re-fetch even if already set
"""

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv(Path(__file__).parent.parent / ".env")

# Import helpers from import_braze
sys.path.insert(0, str(Path(__file__).parent))
from import_braze import init_config, braze_request, parse_date, get_config

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"
BRAZE_BRANDS = {"HAV", "CZ", "ID", "BUR", "STF"}


def load_yaml(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"  ERROR reading {path.name}: {e}", file=sys.stderr)
        return None


def save_yaml(path: Path, data: dict) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return True
    except Exception as e:
        print(f"  ERROR writing {path.name}: {e}", file=sys.stderr)
        return False


def fetch_details(campaign_id: str) -> dict | None:
    """Fetch /campaigns/details and return the full response dict."""
    try:
        data = braze_request("campaigns/details", {"campaign_id": campaign_id})
        if data and isinstance(data, dict):
            return data
    except Exception as e:
        print(f"  API error for {campaign_id}: {e}", file=sys.stderr)
    return None


def needs_backfill(data: dict, force: bool) -> bool:
    if force:
        return True
    return "schedule_type" not in data


def apply_schedule_type(data: dict, details: dict) -> bool:
    """Apply schedule_type from Braze details response. Returns True if changed."""
    st = details.get("schedule_type")
    if st and data.get("schedule_type") != st:
        data["schedule_type"] = st
        return True
    return False


def reorder_dates(dates: dict) -> dict:
    """Return dates dict with canonical key order."""
    key_order = ["created", "send_date", "scheduled_time", "local_time_send", "sto",
                 "first_sent", "last_sent"]
    ordered = {}
    for key in key_order:
        if key in dates:
            ordered[key] = dates[key]
    for key, val in dates.items():
        if key not in ordered:
            ordered[key] = val
    return ordered


def main():
    parser = argparse.ArgumentParser(description="Backfill scheduling metadata from Braze API")
    parser.add_argument("--brand", help="Only process this brand (e.g. ID, HAV, BUR, CZ, STF)")
    parser.add_argument("--limit", type=int, help="Stop after N campaigns")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't write")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if fields already set")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between API calls (default: 1.5)")
    args = parser.parse_args()

    brands_to_process = {args.brand.upper()} if args.brand else BRAZE_BRANDS

    yaml_files = sorted(CAMPAIGNS_DIR.glob("*.yaml"))
    print(f"Found {len(yaml_files)} YAML files total\n")

    # Group by brand so we can init config once per brand
    by_brand: dict[str, list[tuple[Path, dict]]] = {}
    skipped_not_braze = 0
    skipped_no_id = 0

    for path in yaml_files:
        data = load_yaml(path)
        if data is None:
            continue

        brand = data.get("brand", "")
        if brand not in brands_to_process:
            continue

        # Skip canvases, canvas steps, and Klaviyo campaigns
        # /campaigns/details only works for batch campaign IDs, not canvas IDs
        braze_type = data.get("braze_type", "")
        if braze_type in ("canvas", "canvas_step"):
            skipped_not_braze += 1
            continue

        # Klaviyo campaigns have klaviyo_type set
        if data.get("klaviyo_type"):
            skipped_not_braze += 1
            continue

        campaign_id = data.get("id") or data.get("braze_id")
        if not campaign_id:
            skipped_no_id += 1
            continue

        if not needs_backfill(data, args.force):
            continue

        by_brand.setdefault(brand, []).append((path, data))

    total_candidates = sum(len(v) for v in by_brand.values())
    print(f"Candidates needing backfill : {total_candidates}")
    print(f"Skipped (canvas/Klaviyo)   : {skipped_not_braze}")
    print(f"Skipped (no campaign ID)   : {skipped_no_id}")
    if args.limit:
        print(f"Processing limit           : {args.limit}")
    print()

    processed = 0
    updated = 0
    errors = 0

    for brand, items in sorted(by_brand.items()):
        print(f"--- {brand} ({len(items)} campaigns) ---")
        try:
            init_config(brand)
        except SystemExit:
            print(f"  Cannot init config for {brand} — skipping")
            continue

        for path, data in items:
            if args.limit and processed >= args.limit:
                break

            campaign_id = data.get("id") or data.get("braze_id")
            name = data.get("name", "")[:70]
            processed += 1

            details = fetch_details(campaign_id)
            if details is None:
                print(f"  ERROR  : {name}")
                errors += 1
            else:
                changed = apply_schedule_type(data, details)
                st = data.get("schedule_type", "?")

                if args.dry_run:
                    print(f"  {st:20s} {name}")
                elif changed:
                    if save_yaml(path, data):
                        updated += 1
                        print(f"  {st:20s} {name}")
                    else:
                        errors += 1
                else:
                    print(f"  (no change) {name}")

            if not args.dry_run:
                time.sleep(args.delay)

        if args.limit and processed >= args.limit:
            break

    print(f"\nResults:")
    print(f"  Fetched  : {processed}")
    print(f"  Updated  : {updated}")
    print(f"  Errors   : {errors}")
    if args.dry_run:
        print("\n(dry-run — no files written)")


if __name__ == "__main__":
    main()

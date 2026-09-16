#!/usr/bin/env python3
"""
Backfill analytics for Klaviyo campaigns and flows.

The campaign-values-reports endpoint has a strict daily quota (~20 calls before a ~20h lockout).
Use --mode timeframe (default) for maximum efficiency: one API call per brand for the full year.
Use --mode batch (legacy) to filter by campaign ID batches (--batch-size default: 100).

The flow-values-reports endpoint has a separate (more generous) quota. Use --include-flows
to also backfill triggered journey analytics (grouped by flow_message_id).

Run AFTER the daily quota resets (~20 hours after last exhaustion).

Usage:
    # Recommended: campaigns + flows in one run (timeframe mode, 1-2 API calls each)
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode timeframe --include-flows
    uv run python scripts/backfill_klaviyo_analytics.py --brand TE --mode timeframe --include-flows

    # Campaigns only
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode timeframe

    # Flows only
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --flows-only

    # Batch mode (legacy): 100 campaign IDs per call (~22-33 calls/brand)
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode batch
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode batch --batch-size 50
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode batch --batch-size 1  # one-at-a-time

    # Limit to recent campaigns
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --days 14

    # Dry run / debug
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --limit 10 --dry-run
    uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode batch --debug

Options:
    --brand NAME       Brand code (TI, TE)
    --mode MODE        Query mode: timeframe (default) or batch
    --include-flows    Also backfill triggered flow analytics (flow-values-reports endpoint)
    --flows-only       Only backfill flows, skip campaign backfill
    --days N           Only backfill campaigns sent within the last N days (e.g. --days 14)
    --batch-size N     [batch mode] Campaign IDs per API call (default: 100)
    --delay SECS       [batch mode] Seconds between batch API calls (default: 2)
    --limit N          Max campaigns to process (for testing)
    --dry-run          Show what would be updated without writing
    --force            Re-fetch analytics even if non-zero values already exist
    --debug            [batch mode] Print raw API response to inspect response structure
"""

from __future__ import annotations

import os
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from utils.klaviyo_client import KlaviyoClient


KLAVIYO_BRANDS = {"TI", "TE"}


def find_klaviyo_campaigns(campaigns_dir: Path, brand: str, force: bool = False) -> list[dict]:
    """Find Klaviyo campaign YAMLs with zero or missing analytics."""
    results = []
    for f in sorted(campaigns_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data:
            continue
        if data.get("brand") != brand:
            continue
        if not data.get("klaviyo_type") == "campaign":
            continue  # skip flows — different analytics endpoint needed
        campaign_id = data.get("klaviyo_campaign_id")
        if not campaign_id:
            continue

        perf = data.get("performance_summary", {})
        has_analytics = perf.get("total_sends", 0) > 0

        if has_analytics and not force:
            continue  # already has real data

        results.append({
            "file": f,
            "data": data,
            "campaign_id": campaign_id,
            "name": data.get("name", ""),
            "send_date": (data.get("dates", {}).get("first_sent") or "2024-07-01")[:10],
            "channel": data.get("channel", "email"),
        })

    return results


def update_yaml_analytics(filepath: Path, analytics: dict) -> None:
    """Update the performance_summary in a YAML file in-place.

    Merges onto the existing performance_summary rather than replacing it
    wholesale, so brand-specific extra fields (e.g. TE's attributed_revenue/
    attributed_purchases, populated separately from a Klaviyo CSV export with
    a custom conversion metric the standard campaign-values-report API
    doesn't expose) survive a re-backfill instead of being silently dropped.
    """
    data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
    if not data:
        return
    existing = data.get("performance_summary") or {}
    existing.update({
        "total_sends": analytics.get("total_sends", 0),
        "total_delivered": analytics.get("total_delivered", 0),
        "total_opens": analytics.get("total_opens", 0),
        "total_clicks": analytics.get("total_clicks", 0),
        "unique_opens": analytics.get("unique_opens", 0),
        "unique_clicks": analytics.get("unique_clicks", 0),
        "open_rate": analytics.get("open_rate", 0.0),
        "click_rate": analytics.get("click_rate", 0.0),
        "total_open_rate": analytics.get("total_open_rate", 0.0),
        "total_click_rate": analytics.get("total_click_rate", 0.0),
        "total_unsubscribes": analytics.get("total_unsubscribes", 0),
    })
    if analytics.get("total_bounces"):
        existing["total_bounces"] = analytics["total_bounces"]
    data["performance_summary"] = existing
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(description="Backfill analytics for Klaviyo campaigns")
    parser.add_argument("--brand", required=True, help="Brand code (TI, TE)")
    parser.add_argument("--mode", choices=["timeframe", "batch"], default="timeframe",
                        help="Query mode: timeframe (default, 1-2 API calls/brand) or batch (100 IDs/call)")
    parser.add_argument("--include-flows", action="store_true",
                        help="Also backfill triggered flow analytics (flow-values-reports endpoint)")
    parser.add_argument("--flows-only", action="store_true",
                        help="Only backfill flows, skip campaign backfill")
    parser.add_argument("--days", type=int, default=None,
                        help="Only backfill campaigns sent within the last N days (e.g. --days 14)")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="[batch mode] Campaign IDs per API call (default: 100; use 1 for one-at-a-time)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="[batch mode] Seconds between batch API calls (default: 2)")
    parser.add_argument("--limit", type=int, default=None, help="Max campaigns to process")
    parser.add_argument("--dry-run", action="store_true", help="Show without writing")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch even if analytics already non-zero")
    parser.add_argument("--debug", action="store_true",
                        help="[batch mode] Print raw API response to inspect response structure")
    args = parser.parse_args()

    brand = args.brand.upper()
    if brand not in KLAVIYO_BRANDS:
        print(f"Error: brand must be one of {KLAVIYO_BRANDS}")
        sys.exit(1)

    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        print(f"Error: KLAVIYO_API_KEY_{brand} not set in .env")
        sys.exit(1)

    client = KlaviyoClient(api_key=api_key, brand=brand)

    campaigns_dir = Path(__file__).parent.parent / "campaigns"

    print(f"[klaviyo:{brand}] Discovering metric IDs...")
    client.discover_metric_ids()

    if not client._placed_order_metric_id:
        print(f"Warning: No metric ID found — analytics calls may fail. Check that your API key has Read access to Metrics.")
        print(f"  Continuing anyway; the API will return an error if the key is insufficient.")


    if not args.flows_only:
        if args.mode == "timeframe":
            _run_timeframe_mode(client, campaigns_dir, brand, args)
        else:
            _run_batch_mode(client, campaigns_dir, brand, args)

    if args.include_flows or args.flows_only:
        _run_flow_mode(client, campaigns_dir, brand, args)


def _run_timeframe_mode(client, campaigns_dir: Path, brand: str, args) -> None:
    """Fetch analytics for all campaigns in the date range in 1-2 API calls."""
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.days:
        start_date = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
        print(f"[klaviyo:{brand}] Fetching analytics for last {args.days} days ({start_date} to {today})...")
    else:
        start_date = "2024-07-01"
        print(f"[klaviyo:{brand}] Fetching analytics for full history ({start_date} to {today})...")

    analytics_map = client.get_all_campaign_analytics(start_date=start_date, end_date=today)
    print(f"  → API returned analytics for {len(analytics_map)} campaigns\n")

    # Build campaign_id → (file, existing_data) map from YAMLs
    yaml_by_cid: dict[str, tuple[Path, dict]] = {}
    for f in sorted(campaigns_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != brand or data.get("klaviyo_type") != "campaign":
            continue
        cid = data.get("klaviyo_campaign_id")
        if cid:
            yaml_by_cid[cid] = (f, data)

    print(f"[klaviyo:{brand}] Found {len(yaml_by_cid)} YAML files on disk")

    all_cids = sorted(analytics_map.keys())
    if args.limit:
        all_cids = all_cids[:args.limit]
        print(f"Limited to {args.limit} campaigns")

    updated = skipped = no_yaml = errors = 0

    for cid in all_cids:
        analytics = analytics_map[cid]
        sends = analytics.get("total_sends", 0)

        if cid not in yaml_by_cid:
            no_yaml += 1
            if args.debug:
                print(f"  [{cid[:8]}] no YAML found")
            continue

        yaml_file, yaml_data = yaml_by_cid[cid]
        existing_sends = yaml_data.get("performance_summary", {}).get("total_sends", 0)
        name = yaml_data.get("name", "")[:60]

        if sends == 0:
            skipped += 1
            if args.debug:
                print(f"  [{cid[:8]}] {name}: no data from API")
            continue

        if existing_sends > 0 and not args.force:
            skipped += 1
            if args.debug:
                print(f"  [{cid[:8]}] {name}: already has {existing_sends:,} sends, skipping")
            continue

        opens = analytics.get("total_opens", 0)
        print(f"  [{cid[:8]}] {name}: {sends:,} sends, {opens:,} opens ({analytics.get('open_rate', 0):.1%})")

        if not args.dry_run:
            try:
                update_yaml_analytics(yaml_file, analytics)
                updated += 1
            except Exception as e:
                print(f"    ERROR writing {yaml_file.name}: {e}")
                errors += 1
        else:
            updated += 1

    # Also count YAMLs with data that weren't in the API response (already zero)
    yamls_still_zero = sum(
        1 for cid, (_, d) in yaml_by_cid.items()
        if cid not in analytics_map and d.get("performance_summary", {}).get("total_sends", 0) == 0
    )

    print(f"\nDone! Updated {updated} files, {skipped} skipped (no data or already filled), "
          f"{no_yaml} in API but no YAML, {errors} errors")
    if yamls_still_zero:
        print(f"  Note: {yamls_still_zero} YAMLs still at zero (not in API response for this date range)")
    if args.dry_run:
        print("  (dry-run — no files written)")


def _run_batch_mode(client, campaigns_dir: Path, brand: str, args) -> None:
    """Fetch analytics in batches of campaign IDs (legacy mode)."""
    campaigns = find_klaviyo_campaigns(campaigns_dir, brand, force=args.force)

    if args.days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).date()
        before = len(campaigns)
        campaigns = [c for c in campaigns if c["send_date"] >= str(cutoff)]
        print(f"Found {len(campaigns)} campaigns needing analytics (last {args.days} days; {before - len(campaigns)} older campaigns skipped)")
    else:
        print(f"Found {len(campaigns)} campaigns needing analytics")

    if args.limit:
        campaigns = campaigns[: args.limit]
        print(f"Limited to {args.limit}")

    if not campaigns:
        print("Nothing to do.")
        return

    batch_size = max(1, args.batch_size)
    n_batches = (len(campaigns) + batch_size - 1) // batch_size
    est_minutes = n_batches * args.delay / 60
    print(f"Batch size: {batch_size} campaigns/call → {n_batches} API calls")
    print(f"Estimated time: {est_minutes:.1f} minutes ({args.delay}s delay between calls)\n")

    updated = 0
    skipped = 0
    errors = 0

    for batch_num, i in enumerate(range(0, len(campaigns), batch_size), 1):
        batch = campaigns[i:i + batch_size]

        if batch_num > 1:
            time.sleep(args.delay)

        # Fetch analytics for the whole batch in one API call
        earliest_date = min(c["send_date"] for c in batch)
        campaign_ids = [c["campaign_id"] for c in batch]

        if batch_size == 1:
            # Legacy single-campaign mode (for debugging or quota conservation)
            camp = batch[0]
            analytics_map = {
                camp["campaign_id"]: client.get_campaign_analytics_report(
                    camp["campaign_id"],
                    start_date=camp["send_date"],
                    channel=camp.get("channel", "email"),
                )
            }
        else:
            analytics_map = client.get_campaign_analytics_batch(
                campaign_ids, start_date=earliest_date, debug=args.debug and batch_num == 1
            )

        for camp in batch:
            cid = camp["campaign_id"]
            analytics = analytics_map.get(cid, client._empty_analytics())
            sends = analytics.get("total_sends", 0)
            opens = analytics.get("total_opens", 0)
            name = camp["name"][:60]

            if sends == 0:
                skipped += 1
                status = "no data (0 sends)"
            else:
                status = f"{sends:,} sends, {opens:,} opens ({analytics.get('open_rate', 0):.1%})"

            print(f"  [{cid[:8]}] {name}: {status}")

            if sends > 0 and not args.dry_run:
                try:
                    update_yaml_analytics(camp["file"], analytics)
                    updated += 1
                except Exception as e:
                    print(f"    ERROR writing {camp['file'].name}: {e}")
                    errors += 1

        have_data = sum(1 for c in batch if analytics_map.get(c["campaign_id"], {}).get("total_sends", 0) > 0)
        print(f"[batch {batch_num}/{n_batches}] {len(batch)} campaigns, {have_data} with data\n")

    print(f"Done! Updated {updated} files, {skipped} no data, {errors} errors")
    if args.dry_run:
        print("  (dry-run — no files written)")


def _run_flow_mode(client, campaigns_dir: Path, brand: str, args) -> None:
    """Fetch analytics for all triggered flow messages and write to YAML files."""
    print(f"\n[klaviyo:{brand}] --- Flow analytics backfill ---")

    # Discover flow YAML files (klaviyo_type: flow, have klaviyo_message_id)
    flow_files: list[tuple[Path, dict, str]] = []  # (path, data, message_id)
    for f in sorted(campaigns_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != brand or data.get("klaviyo_type") != "flow":
            continue
        mid = data.get("klaviyo_message_id")
        if not mid:
            continue
        flow_files.append((f, data, mid))

    print(f"[klaviyo:{brand}] Found {len(flow_files)} flow YAML files needing analytics")
    if not flow_files:
        print("  Nothing to do.")
        return

    # Fetch all flow analytics in one (or a few) API calls
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    analytics_map = client.get_all_flow_analytics(start_date="2019-01-01", end_date=today)
    print(f"  → API returned analytics for {len(analytics_map)} flow messages\n")

    updated = skipped = errors = 0
    limit = args.limit

    for f, data, mid in flow_files:
        if limit is not None and updated + skipped >= limit:
            break

        analytics = analytics_map.get(mid)
        if not analytics or analytics.get("total_sends", 0) == 0:
            skipped += 1
            if args.debug:
                name = data.get("name", "")[:60]
                print(f"  [{mid}] {name}: no data from API")
            continue

        sends = analytics["total_sends"]
        opens = analytics["total_opens"]
        name = data.get("name", "")[:60]
        print(f"  [{mid}] {name}: {sends:,} sends, {opens:,} opens ({analytics.get('open_rate', 0):.1%})")

        if not args.dry_run:
            try:
                update_yaml_analytics(f, analytics)
                updated += 1
            except Exception as e:
                print(f"    ERROR writing {f.name}: {e}")
                errors += 1
        else:
            updated += 1

    print(f"\nFlow backfill done! Updated {updated}, {skipped} no data from API, {errors} errors")
    if args.dry_run:
        print("  (dry-run — no files written)")


if __name__ == "__main__":
    main()

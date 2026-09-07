#!/usr/bin/env python3
"""
Backfill analytics for campaigns missing open rate data.

Uses each campaign's last_sent date to fetch analytics from the correct time range.

Usage:
    uv run python scripts/backfill_analytics.py --brand HAV
    uv run python scripts/backfill_analytics.py --brand CZ --workers 10
    uv run python scripts/backfill_analytics.py --all

    # Force-refresh recent campaigns (e.g. to capture late-arriving opens)
    uv run python scripts/backfill_analytics.py --brand HAV --force --since 2026-03-22
    uv run python scripts/backfill_analytics.py --all --force --since 2026-03-22
"""

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import yaml

from import_braze import (
    init_config,
    get_campaign_analytics,
    get_campaign_details,
    CONFIG,
)


def load_campaigns_missing_analytics(campaigns_dir, brand=None, force=False, since_date=None):
    """Load campaigns that don't have open_rate data (or all campaigns if force=True).

    Args:
        force: If True, include campaigns that already have analytics (for refreshing)
        since_date: If set (datetime.date), only include campaigns with last_sent >= since_date
    """
    campaigns = []

    for f in campaigns_dir.glob("*.yaml"):
        if f.name.startswith("_"):
            continue

        with open(f) as file:
            data = yaml.safe_load(file)
            if not data:
                continue

        # Skip Klaviyo campaigns — they use a different analytics endpoint
        if data.get("klaviyo_type"):
            continue

        # Skip canvas and canvas_step records — handled by flatten_canvases.py
        if data.get("braze_type") in ("canvas", "canvas_step"):
            continue

        # Filter by brand if specified
        if brand and data.get("brand") != brand:
            continue

        # Check if missing analytics (skip check when --force)
        perf = data.get("performance_summary", {})
        if not force and perf.get("open_rate"):
            continue  # Already has analytics

        # Need braze_id and a date to fetch from
        braze_id = data.get("braze_id") or data.get("id")
        if not braze_id:
            continue

        # Get last_sent date, fall back to created date, then try campaign name
        dates = data.get("dates", {})
        last_sent = dates.get("last_sent") or dates.get("created")

        # Try to extract date from campaign name if not in dates field
        if not last_sent:
            name = data.get("name", "")
            date_match = re.search(r'(\d{4})[-_](\d{1,2})[-_](\d{1,2})', name)
            if date_match:
                year, month, day = date_match.groups()
                last_sent = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        if not last_sent:
            continue

        # Filter by --since date if provided
        if since_date is not None:
            try:
                if "T" in str(last_sent):
                    last_sent_dt = datetime.fromisoformat(str(last_sent).replace("Z", "+00:00")).date()
                else:
                    last_sent_dt = datetime.strptime(str(last_sent)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if last_sent_dt < since_date:
                continue

        campaigns.append({
            "file": f,
            "data": data,
            "braze_id": braze_id,
            "last_sent": last_sent,
        })

    return campaigns


def fetch_and_update_analytics(campaign_info, dry_run=False):
    """Fetch analytics for a campaign and update its file."""
    braze_id = campaign_info["braze_id"]
    last_sent_str = campaign_info["last_sent"]
    data = campaign_info["data"]
    filepath = campaign_info["file"]

    # Parse last_sent date and create a range around it
    try:
        last_sent = datetime.strptime(last_sent_str, "%Y-%m-%d")
    except ValueError:
        try:
            # Handle full ISO timestamps like "2026-03-15T13:18:15+00:00"
            last_sent = datetime.fromisoformat(last_sent_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None, f"Invalid date: {last_sent_str}"

    # Fetch analytics for 14 days after the send (captures delayed opens)
    start_date = last_sent - timedelta(days=1)
    end_date = last_sent + timedelta(days=14)

    # Don't fetch into the future — Braze requires ending_at to be in the past
    yesterday = datetime.now() - timedelta(days=1)
    if end_date > yesterday:
        end_date = yesterday

    # Fetch analytics
    analytics = get_campaign_analytics(braze_id, start_date, end_date)

    if not analytics or "data" not in analytics:
        return None, "No analytics data returned"

    # Parse analytics (same logic as import_braze.py)
    total_sends = 0
    total_opens = 0
    total_clicks = 0
    total_revenue = 0
    total_delivered = 0
    total_bounces = 0
    total_unsubscribes = 0

    for day_data in analytics["data"]:
        messages = day_data.get("messages", {})
        for channel, variants in messages.items():
            if isinstance(variants, list):
                for variant in variants:
                    total_sends += variant.get("sent", 0)
                    total_opens += variant.get("unique_opens", 0)
                    total_clicks += variant.get("unique_clicks", 0)
                    total_revenue += variant.get("revenue", 0)
                    total_delivered += variant.get("delivered", 0)
                    total_bounces += variant.get("bounces", 0)
                    total_unsubscribes += variant.get("unsubscribes", 0)

        # Also check top-level (older API format)
        if not messages:
            total_sends += day_data.get("sent", 0)
            total_opens += day_data.get("unique_opens", 0)
            total_clicks += day_data.get("unique_clicks", 0)
            total_revenue += day_data.get("revenue", 0)

    if total_sends == 0:
        return None, "No sends in analytics data"

    # Build performance summary
    perf_summary = {
        "total_sends": total_sends,
        "total_delivered": total_delivered,
        "total_opens": total_opens,
        "total_clicks": total_clicks,
        "open_rate": round(total_opens / total_sends, 4),
        "click_rate": round(total_clicks / total_sends, 4),
    }

    if total_revenue > 0:
        perf_summary["total_revenue"] = round(total_revenue, 2)
    if total_bounces > 0:
        perf_summary["total_bounces"] = total_bounces
    if total_unsubscribes > 0:
        perf_summary["total_unsubscribes"] = total_unsubscribes

    # Patch subject lines if any sends are missing them.
    # Campaigns imported before or right at send time may have an empty subject
    # because the daily import uses --skip-existing and never re-fetches.
    sends = data.get("sends", [])
    missing_subject = not sends or any(not s.get("subject", "").strip() for s in sends)
    if missing_subject:
        details = get_campaign_details(braze_id)
        if details:
            messages = details.get("messages", {})
            if isinstance(messages, dict):
                # Build list of (variant_key, subject, preheader, name) for email variants
                email_variants = []
                for variant_key, msg in messages.items():
                    if isinstance(msg, dict) and msg.get("channel") == "email":
                        subject = (msg.get("subject") or "").strip()
                        preheader = (msg.get("preheader") or "").strip()
                        msg_name = msg.get("name") or variant_key
                        if subject:
                            email_variants.append((variant_key, subject, preheader, msg_name))

                if email_variants:
                    print(f"  [subject] patching {len(email_variants)} variant(s) for {data.get('name', '')[:50]}")
                    if sends:
                        # Patch existing send entries that are missing a subject
                        for i, send in enumerate(sends):
                            if not send.get("subject", "").strip() and i < len(email_variants):
                                _, subject, preheader, _ = email_variants[i]
                                send["subject"] = subject
                                if preheader:
                                    send["preheader"] = preheader
                    else:
                        # No sends array yet — build one from the details response
                        sends = []
                        for variant_key, subject, preheader, msg_name in email_variants:
                            sends.append({
                                "id": variant_key,
                                "channel": "email",
                                "name": msg_name,
                                "subject": subject,
                                "preheader": preheader,
                            })
                        data["sends"] = sends

    # Update data
    data["performance_summary"] = perf_summary

    if not dry_run:
        with open(filepath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return perf_summary, None


def main():
    parser = argparse.ArgumentParser(description="Backfill analytics for campaigns")
    parser.add_argument("--brand", type=str, help="Brand to backfill (HAV, CZ, etc.)")
    parser.add_argument("--all", action="store_true", help="Backfill all brands")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers")
    parser.add_argument("--limit", type=int, help="Limit number of campaigns")
    parser.add_argument("--force", action="store_true", help="Re-fetch analytics even if already present")
    parser.add_argument("--since", type=str, help="Only process campaigns with last_sent >= this date (YYYY-MM-DD)")
    args = parser.parse_args()

    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return

    since_date = None
    if args.since:
        try:
            since_date = datetime.strptime(args.since, "%Y-%m-%d").date()
            print(f"Filtering to campaigns sent on or after {since_date}")
        except ValueError:
            print(f"Error: --since must be YYYY-MM-DD, got: {args.since}")
            return

    script_dir = Path(__file__).parent
    campaigns_dir = script_dir.parent / "campaigns"

    # Determine brands to process
    if args.all:
        brands = ["HAV", "CZ", "STF", "BUR", "ID"]
    else:
        brands = [args.brand.upper()]

    total_updated = 0
    total_failed = 0

    for brand in brands:
        print(f"\n{'='*60}")
        print(f"Processing {brand}")
        print(f"{'='*60}")

        # Initialize config for this brand's API
        init_config(brand)

        # Load campaigns (missing analytics, or all if --force)
        campaigns = load_campaigns_missing_analytics(campaigns_dir, brand, force=args.force, since_date=since_date)
        label = "campaigns to refresh" if args.force else "campaigns missing analytics"
        print(f"Found {len(campaigns)} {label}")

        if not campaigns:
            continue

        if args.limit:
            campaigns = campaigns[:args.limit]
            print(f"Limited to {args.limit} campaigns")

        # Thread-safe counters
        print_lock = threading.Lock()
        updated_count = [0]
        failed_count = [0]
        counter_lock = threading.Lock()

        def process_campaign(campaign_info):
            result, error = fetch_and_update_analytics(campaign_info, args.dry_run)

            with counter_lock:
                if result:
                    updated_count[0] += 1
                    count = updated_count[0]
                else:
                    failed_count[0] += 1
                    count = updated_count[0]

            with print_lock:
                name = campaign_info["data"].get("name", "")[:45]
                if result:
                    open_rate = result.get("open_rate", 0) * 100
                    status = f"open_rate={open_rate:.1f}%"
                    if args.dry_run:
                        status += " (dry-run)"
                    print(f"[{count}/{len(campaigns)}] {name}... {status}")
                else:
                    print(f"[SKIP] {name}: {error}")

            return result

        # Process in parallel
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_campaign, c): c for c in campaigns}
            for future in as_completed(futures):
                pass

        print(f"\n{brand}: Updated {updated_count[0]}, Failed {failed_count[0]}")
        total_updated += updated_count[0]
        total_failed += failed_count[0]

    print(f"\n{'='*60}")
    print(f"TOTAL: Updated {total_updated}, Failed {total_failed}")


if __name__ == "__main__":
    main()

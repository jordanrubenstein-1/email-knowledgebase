#!/usr/bin/env python3
"""
Quick diagnostic: Check canvas structure to debug step name matching.
Fetches just a few canvases and shows their step/message names.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

from braze_api_client import get_all_canvases, get_canvas_details, braze_request


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Debug canvas structure")
    ap.add_argument("--brand", type=str, required=True, choices=["CZ", "ID", "BUR"])
    ap.add_argument("--limit", type=int, default=3, help="Number of canvases to inspect")
    args = ap.parse_args()
    
    brand = args.brand.upper()
    print(f"Fetching canvases for {brand}...")
    
    # Get all canvases (don't filter by canvas name - brand is in step names)
    canvases = get_all_canvases(brand=brand)
    print(f"Total canvases from API: {len(canvases)}")
    
    print(f"Found {len(canvases)} canvases. Inspecting first {args.limit}:\n")
    
    for i, canvas in enumerate(canvases[:args.limit]):
        canvas_id = canvas["id"]
        canvas_name = canvas["name"]
        print(f"{'='*60}")
        print(f"Canvas {i+1}: {canvas_name}")
        print(f"{'='*60}")
        
        details = get_canvas_details(canvas_id, brand=brand)
        if not details:
            print("  (no details available)")
            continue
        
        steps = details.get("steps", [])
        print(f"\n  Steps ({len(steps)} total):")
        
        for step in steps[:10]:  # Show first 10 steps
            step_id = step.get("id", "?")
            step_name = step.get("name", "(no name)")
            step_type = step.get("type", "?")
            print(f"\n  Step: '{step_name}'")
            print(f"    ID: {step_id}")
            print(f"    Type: {step_type}")
            
            # Check for messages within step
            messages = step.get("messages", {})
            if messages and isinstance(messages, dict):
                print(f"    Messages ({len(messages)}):")
                for msg_var_id, msg_data in messages.items():
                    if isinstance(msg_data, dict):
                        msg_name = msg_data.get("name", "(no name)")
                        channel = msg_data.get("channel", "?")
                        has_brand = brand in msg_name.upper() if msg_name else False
                        marker = " <-- MATCHES BRAND" if has_brand else ""
                        print(f"      - [{channel}] '{msg_name}' (var: {msg_var_id[:8]}...){marker}")
            else:
                print("    Messages: (none or empty)")
            
            # Also mark if step name has brand
            if brand in step_name.upper():
                print(f"    ^ Step name contains '{brand}'")
        
        if len(steps) > 10:
            print(f"\n  ... and {len(steps) - 10} more steps")
        
        print()
    
    # Also show GA4 TRG campaigns
    print(f"\n{'='*60}")
    print("GA4 TRG Campaigns (for comparison)")
    print(f"{'='*60}")
    
    try:
        from import_ga4_metrics_snowflake import query_ga4_for_lifecycle_report
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=7)
        ga4_df = query_ga4_for_lifecycle_report(brand, start_dt, end_dt)
        
        trg_campaigns = ga4_df[ga4_df["Session campaign"].astype(str).str.contains("TRG", na=False)]["Session campaign"].unique()
        print(f"\nFound {len(trg_campaigns)} TRG campaigns in GA4 (last 7 days):")
        for tc in sorted(trg_campaigns)[:20]:
            print(f"  - {tc}")
        if len(trg_campaigns) > 20:
            print(f"  ... and {len(trg_campaigns) - 20} more")
    except Exception as e:
        print(f"Could not fetch GA4 data: {e}")


if __name__ == "__main__":
    main()

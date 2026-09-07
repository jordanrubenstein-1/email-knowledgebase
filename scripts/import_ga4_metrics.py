#!/usr/bin/env python3
"""
Import GA4 conversion metrics (sessions, purchases, revenue) for campaigns and canvases.

Matches campaigns to GA4 data using UTM parameters and date-based attribution windows,
then enriches campaign YAML files with GA4 metrics.

Usage:
    uv run python scripts/import_ga4_metrics.py --brand HAV
    uv run python scripts/import_ga4_metrics.py --all --attribution-days 14
    uv run python scripts/import_ga4_metrics.py --brand CZ --dry-run
    uv run python scripts/import_ga4_metrics.py --brand HAV --days 30

Options:
    --brand NAME           Brand to import (HAV, CZ, ID, BUR, STF)
    --all                  Import for all brands
    --attribution-days N   Attribution window in days (default: 7)
    --days N               Only process campaigns from last N days
    --dry-run              Preview matches without writing files
    --workers N            Parallel workers for API requests (default: 5)
"""

import os
import re
import sys
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Optional, Dict, Any

from dotenv import load_dotenv
import yaml
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    Dimension,
    Metric,
    DateRange,
    Filter,
    FilterExpression,
    StringFilter,
)

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Brand aliases for normalization
BRAND_ALIASES = {
    "id": "ID",
    "interior define": "ID",
    "ti": "TI",
    "the inside": "TI",
    "cz": "CZ",
    "the citizenry": "CZ",
    "citizenry": "CZ",
    "hav": "HAV",
    "havenly": "HAV",
    "bur": "BUR",
    "burrow": "BUR",
    "stf": "STF",
    "st. frank": "STF",
    "st frank": "STF",
}

def normalize_brand(brand):
    """Normalize brand name to standard code."""
    if not brand:
        return None
    return BRAND_ALIASES.get(brand.lower(), brand.upper())


def get_ga4_property_id(brand):
    """Get GA4 property ID for a brand from environment."""
    brand = normalize_brand(brand)
    if not brand:
        return None
    
    property_id = os.environ.get(f"GA4_PROPERTY_ID_{brand}")
    if not property_id:
        print(f"Warning: GA4_PROPERTY_ID_{brand} not set in .env")
        return None
    return property_id


def get_ga4_client():
    """Initialize GA4 Data API client using service account."""
    service_account_path = os.environ.get("GA4_SERVICE_ACCOUNT_PATH")
    if not service_account_path:
        print("Error: GA4_SERVICE_ACCOUNT_PATH not set in .env")
        print("Set it to the path of your Google Cloud service account JSON key file")
        sys.exit(1)
    
    if not os.path.exists(service_account_path):
        print(f"Error: Service account file not found: {service_account_path}")
        sys.exit(1)
    
    # Set environment variable for Google auth
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = service_account_path
    
    try:
        client = BetaAnalyticsDataClient()
        return client
    except Exception as e:
        print(f"Error initializing GA4 client: {e}")
        sys.exit(1)


def determine_attribution_window(campaign_data, default_days=7):
    """Determine attribution window based on campaign type."""
    # Canvas/triggered campaigns get longer window
    if campaign_data.get("braze_type") == "canvas_step":
        return 14
    
    # Sale campaigns might want shorter window (but default to standard)
    category = campaign_data.get("category", "")
    if "sale" in category.lower():
        return default_days  # Could be 1 day, but using default for now
    
    return default_days


def normalize_campaign_name_for_ga4(campaign_name):
    """Normalize campaign name to match GA4 UTM campaign parameter patterns.
    
    Braze may use different naming conventions. This attempts to match common patterns.
    """
    if not campaign_name:
        return None
    
    # Remove common prefixes/suffixes that might not be in UTM
    name = campaign_name.strip()
    
    # Try to extract the core campaign name
    # Braze names often have format: P_EM_2025_07_20_HAV_PC_Summer_Sale_Reminder_PT
    # UTM might just be: Summer_Sale_Reminder or similar
    
    # For now, return as-is - matching logic will need to be flexible
    return name


def query_campaign_metrics(
    client,
    property_id,
    campaign_name,
    braze_id,
    start_date,
    end_date,
    attribution_days=7,
    max_retries=3
):
    """Query GA4 for campaign metrics using UTM parameters and date range.
    
    Returns dict with sessions, purchases, revenue, or None on error.
    """
    
    # Build date range
    date_range = DateRange(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )
    
    # Dimensions to query
    dimensions = [
        Dimension(name="sessionSourceMedium"),
        Dimension(name="campaignName"),
        Dimension(name="sessionDefaultChannelGroup"),
    ]
    
    # Metrics to query
    metrics = [
        Metric(name="sessions"),
        Metric(name="purchases"),
        Metric(name="totalRevenue"),
    ]
    
    # Filter for email traffic
    dimension_filter = FilterExpression(
        filter=Filter(
            field_name="sessionSourceMedium",
            string_filter=StringFilter(
                match_type=StringFilter.MatchType.CONTAINS,
                value="email",
                case_sensitive=False,
            )
        )
    )
    
    # Build request
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[date_range],
        dimensions=dimensions,
        metrics=metrics,
        dimension_filter=dimension_filter,
    )
    
    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        try:
            response = client.run_report(request)
            break
        except Exception as e:
            if attempt == max_retries - 1:
                # Last attempt failed
                return None
            # Exponential backoff: 1s, 2s, 4s
            wait_time = 2 ** attempt
            time.sleep(wait_time)
            continue
    
    # Aggregate results
    total_sessions = 0
    total_purchases = 0
    total_revenue = 0.0
    
    # Match rows that could be from this campaign
    normalized_campaign_name = normalize_campaign_name_for_ga4(campaign_name)
    campaign_name_lower = (normalized_campaign_name or "").lower()
    braze_id_lower = (braze_id or "").lower()
    
    # Extract key parts from campaign name for better matching
    # Braze names like "P_EM_2025_07_20_HAV_PC_Summer_Sale_Reminder_PT"
    # might be in GA4 as "Summer_Sale_Reminder" or similar
    campaign_keywords = []
    if campaign_name:
        # Split on common separators and take meaningful parts
        parts = re.split(r'[_\s-]+', campaign_name)
        # Filter out dates, prefixes, and short codes
        for part in parts:
            part_lower = part.lower()
            # Skip dates, single letters, common prefixes
            if (len(part) > 2 and 
                not part.isdigit() and 
                not part_lower in ['p', 'em', 'pc', 'pt', 'd', 'hav', 'cz', 'id', 'bur', 'stf']):
                campaign_keywords.append(part_lower)
    
    for row in response.rows:
        # Check if this row matches our campaign
        # Look at campaignName dimension
        campaign_dim = None
        for dim_value in row.dimension_values:
            if dim_value.name == "campaignName":
                campaign_dim = dim_value.value
                break
        
        if not campaign_dim:
            continue
        
        # Try to match campaign name or braze_id
        campaign_dim_lower = campaign_dim.lower()
        matches = False
        
        # Exact match or substring match
        if campaign_name_lower and (
            campaign_name_lower == campaign_dim_lower or
            campaign_name_lower in campaign_dim_lower or
            campaign_dim_lower in campaign_name_lower
        ):
            matches = True
        
        # Match if braze_id appears in campaign name
        if braze_id_lower and braze_id_lower in campaign_dim_lower:
            matches = True
        
        # Match if key campaign keywords appear
        if campaign_keywords:
            keyword_matches = sum(1 for kw in campaign_keywords if kw in campaign_dim_lower)
            # Require at least 2 keywords to match (to avoid false positives)
            if keyword_matches >= min(2, len(campaign_keywords)):
                matches = True
        
        if matches:
            # Aggregate metrics
            for metric_value in row.metric_values:
                metric_name = metric_value.name
                value = float(metric_value.value) if metric_value.value else 0.0
                
                if metric_name == "sessions":
                    total_sessions += int(value)
                elif metric_name == "purchases":
                    total_purchases += int(value)
                elif metric_name == "totalRevenue":
                    total_revenue += value
    
    return {
        "sessions": total_sessions,
        "purchases": total_purchases,
        "revenue": round(total_revenue, 2),
    }


def load_campaigns(campaigns_dir, brand=None, days_limit=None):
    """Load campaign YAML files, optionally filtered by brand and date."""
    campaigns = []
    
    for f in campaigns_dir.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        
        try:
            with open(f) as file:
                data = yaml.safe_load(file)
                if not data:
                    continue
        except Exception as e:
            print(f"Warning: Error loading {f.name}: {e}")
            continue
        
        # Filter by brand
        if brand and data.get("brand") != brand:
            continue
        
        # Filter by date if specified
        if days_limit:
            dates = data.get("dates", {})
            first_sent = dates.get("first_sent")
            if first_sent:
                try:
                    if isinstance(first_sent, str):
                        first_sent_dt = datetime.fromisoformat(first_sent.replace("Z", "+00:00"))
                    else:
                        first_sent_dt = first_sent
                    
                    if isinstance(first_sent_dt, datetime):
                        days_ago = (datetime.now(first_sent_dt.tzinfo) - first_sent_dt).days
                        if days_ago > days_limit:
                            continue
                except Exception:
                    pass  # Skip if date parsing fails
        
        campaigns.append({
            "file": f,
            "data": data,
        })
    
    return campaigns


def update_campaign_with_ga4(campaign_info, ga4_metrics, attribution_days, dry_run=False):
    """Update campaign YAML file with GA4 metrics."""
    filepath = campaign_info["file"]
    data = campaign_info["data"]
    
    # Ensure performance_summary exists
    if "performance_summary" not in data:
        data["performance_summary"] = {}
    
    # Add or update GA4 metrics
    data["performance_summary"]["ga4"] = {
        "sessions": ga4_metrics["sessions"],
        "purchases": ga4_metrics["purchases"],
        "revenue": ga4_metrics["revenue"],
        "attribution_window_days": attribution_days,
        "last_synced": datetime.now().isoformat(),
    }
    
    if not dry_run:
        with open(filepath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return data["performance_summary"]["ga4"]


def process_campaign(
    campaign_info,
    client,
    property_id,
    default_attribution_days,
    dry_run=False,
):
    """Process a single campaign - fetch GA4 metrics and update YAML."""
    data = campaign_info["data"]
    filepath = campaign_info["file"]
    
    brand = data.get("brand")
    campaign_name = data.get("name", "")
    braze_id = data.get("braze_id") or data.get("id")
    dates = data.get("dates", {})
    first_sent = dates.get("first_sent")
    
    if not first_sent:
        return None, "No first_sent date"
    
    # Parse date
    try:
        if isinstance(first_sent, str):
            first_sent_dt = datetime.fromisoformat(first_sent.replace("Z", "+00:00"))
        else:
            first_sent_dt = first_sent
        
        if not isinstance(first_sent_dt, datetime):
            return None, "Invalid date format"
    except Exception as e:
        return None, f"Date parsing error: {e}"
    
    # Determine attribution window
    attribution_days = determine_attribution_window(data, default_attribution_days)
    
    # Calculate date range
    start_date = first_sent_dt.replace(tzinfo=None)  # Remove timezone for GA4
    end_date = start_date + timedelta(days=attribution_days)
    
    # Don't query into the future
    now = datetime.now()
    if end_date > now:
        end_date = now
    
    # Query GA4
    ga4_metrics = query_campaign_metrics(
        client,
        property_id,
        campaign_name,
        braze_id,
        start_date,
        end_date,
        attribution_days,
    )
    
    if ga4_metrics is None:
        return None, "GA4 API error"
    
    # Even if no matches, return zero metrics (not an error)
    # This allows us to track that we tried to sync
    
    # Update campaign file
    updated = update_campaign_with_ga4(
        campaign_info,
        ga4_metrics,
        attribution_days,
        dry_run=dry_run,
    )
    
    return updated, None


def main():
    parser = argparse.ArgumentParser(
        description="Import GA4 conversion metrics for campaigns"
    )
    parser.add_argument("--brand", type=str, help="Brand to import (HAV, CZ, etc.)")
    parser.add_argument("--all", action="store_true", help="Import for all brands")
    parser.add_argument(
        "--attribution-days",
        type=int,
        default=7,
        help="Attribution window in days (default: 7)",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Only process campaigns from last N days",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Parallel workers (default: 5, GA4 limit is 10 req/sec)",
    )
    args = parser.parse_args()
    
    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return
    
    # Initialize GA4 client
    print("Initializing GA4 client...")
    client = get_ga4_client()
    
    script_dir = Path(__file__).parent
    campaigns_dir = script_dir.parent / "campaigns"
    
    # Determine brands to process
    if args.all:
        brands = ["HAV", "CZ", "STF", "BUR", "ID", "TI"]
    else:
        brands = [normalize_brand(args.brand)]
    
    total_updated = 0
    total_failed = 0
    total_no_match = 0
    
    for brand in brands:
        print(f"\n{'='*60}")
        print(f"Processing {brand}")
        print(f"{'='*60}")
        
        # Get property ID for this brand
        property_id = get_ga4_property_id(brand)
        if not property_id:
            print(f"Skipping {brand} - no GA4 property ID configured")
            continue
        
        # Load campaigns
        campaigns = load_campaigns(campaigns_dir, brand=brand, days_limit=args.days)
        print(f"Found {len(campaigns)} campaigns to process")
        
        if not campaigns:
            continue
        
        # Thread-safe counters
        print_lock = threading.Lock()
        updated_count = [0]
        failed_count = [0]
        no_match_count = [0]
        counter_lock = threading.Lock()
        
        def process_with_lock(campaign_info):
            result, error = process_campaign(
                campaign_info,
                client,
                property_id,
                args.attribution_days,
                dry_run=args.dry_run,
            )
            
            with counter_lock:
                if result:
                    updated_count[0] += 1
                    count = updated_count[0]
                elif error and "GA4 API error" in error:
                    failed_count[0] += 1
                    count = updated_count[0]
                else:
                    # No match or other issue - still count as processed
                    if result is None:
                        no_match_count[0] += 1
                    else:
                        updated_count[0] += 1
                    count = updated_count[0]
            
            with print_lock:
                name = campaign_info["data"].get("name", "")[:50]
                if result:
                    sessions = result.get("sessions", 0)
                    purchases = result.get("purchases", 0)
                    revenue = result.get("revenue", 0)
                    if sessions > 0 or purchases > 0 or revenue > 0:
                        status = f"sessions={sessions}, purchases={purchases}, revenue=${revenue:.2f}"
                    else:
                        status = "no matches"
                    if args.dry_run:
                        status += " (dry-run)"
                    print(f"[{count}/{len(campaigns)}] {name}... {status}")
                else:
                    print(f"[SKIP] {name}: {error}")
            
            # Rate limiting - GA4 allows 10 req/sec, so space out requests
            time.sleep(0.15)  # ~6-7 requests per second to be safe
            
            return result
        
        # Process in parallel (but with rate limiting)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_with_lock, c): c for c in campaigns}
            for future in as_completed(futures):
                pass
        
        print(f"\n{brand}: Updated {updated_count[0]}, No Match {no_match_count[0]}, Failed {failed_count[0]}")
        total_updated += updated_count[0]
        total_failed += failed_count[0]
        total_no_match += no_match_count[0]
    
    print(f"\n{'='*60}")
    print(f"TOTAL: Updated {total_updated}, No Match {total_no_match}, Failed {total_failed}")
    if args.dry_run:
        print("(Dry run - no files were modified)")


if __name__ == "__main__":
    main()


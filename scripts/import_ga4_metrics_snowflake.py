#!/usr/bin/env python3
"""
Import GA4 conversion metrics (sessions, purchases, revenue) from Snowflake for campaigns and canvases.

Uses Session primary/default channel group (Email vs SMS) to attribute traffic—not source/medium—
so GA4 UI metrics match. Filters to Email and SMS only; matches campaigns by name and channel.
Enriches campaign YAML files with GA4 metrics.

Usage:
    uv run python scripts/import_ga4_metrics_snowflake.py --brand HAV
    uv run python scripts/import_ga4_metrics_snowflake.py --all --attribution-days 14
    uv run python scripts/import_ga4_metrics_snowflake.py --brand CZ --dry-run
    uv run python scripts/import_ga4_metrics_snowflake.py --brand HAV --days 30

Options:
    --brand NAME           Brand to import (HAV, CZ, ID, BUR, STF, TI)
    --all                  Import for all brands
    --attribution-days N   Attribution window in days (default: 7)
    --days N               Only process campaigns from last N days
    --dry-run              Preview matches without writing files
"""

import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from collections import defaultdict

from dotenv import load_dotenv
import yaml

try:
    import pandas as pd
except ImportError:
    pd = None

# Import from local snowflake_client module
# Add scripts directory to path so we can import snowflake_client
import sys
from pathlib import Path
scripts_dir = Path(__file__).parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))
from snowflake_client import get_snowflake_client, SnowflakeClient

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


def get_schema_for_brand(brand):
    """Get Snowflake schema name for a brand.
    
    Maps brand codes to their corresponding GA4 landing schemas.
    """
    brand = normalize_brand(brand)
    if not brand:
        return None
    
    # Map brands to their GA4 schemas
    schema_map = {
        "BUR": "LANDING_BURROW_GA4",
        "CZ": "LANDING_CITIZENRY_GA4",
        "ID": "LANDING_INTERIORDEFINE_GA4",
        "HAV": "LANDING_HAVENLY_GA4",
        "STF": "LANDING_ST_FRANK_GA4",
        "TI": "LANDING_THE_INSIDE_GA4",
    }
    
    # Check environment variable override first
    env_key = f"SNOWFLAKE_SCHEMA_{brand}"
    env_schema = os.environ.get(env_key)
    if env_schema:
        return env_schema
    
    # Fall back to mapping
    return schema_map.get(brand) or os.environ.get("SNOWFLAKE_SCHEMA")


def get_table_for_brand(brand):
    """Get Snowflake table name for a brand.
    
    Different brands may use different table names with the same schema.
    """
    brand = normalize_brand(brand)
    if not brand:
        return os.environ.get("SNOWFLAKE_GA4_TABLE", "TRAFFIC_SESSION_PERFORMANCE_DAILY")
    
    # Map brands to their table names.
    # BUR, CZ, ID all use TRAFFIC_SESSION_PERFORMANCE_DAILY (same format, SESSIONCAMPAIGNNAME).
    table_map = {
        "BUR": "TRAFFIC_SESSION_PERFORMANCE_DAILY",
        "CZ": "TRAFFIC_SESSION_PERFORMANCE_DAILY",
        "ID": "TRAFFIC_SESSION_PERFORMANCE_DAILY",
    }
    
    # Check environment variable override first
    env_key = f"SNOWFLAKE_GA4_TABLE_{brand}"
    env_table = os.environ.get(env_key)
    if env_table:
        return env_table
    
    # Fall back to mapping or default
    return table_map.get(brand) or os.environ.get("SNOWFLAKE_GA4_TABLE", "TRAFFIC_SESSION_PERFORMANCE_DAILY")


def _channel_group_column_for_brand(brand):
    """Channel group column for Email/SMS attribution. Matches GA4 UI (not source/medium)."""
    b = normalize_brand(brand) if brand else None
    if b:
        env_key = f"SNOWFLAKE_CHANNEL_GROUP_COLUMN_{b}"
        if os.environ.get(env_key):
            return os.environ[env_key]
    return os.environ.get("SNOWFLAKE_CHANNEL_GROUP_COLUMN", "SESSIONPRIMARYCHANNELGROUP")


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


def extract_campaign_keywords(campaign_name):
    """Extract meaningful keywords from campaign name for matching.
    
    Braze names like "P_EM_2025_07_20_HAV_PC_Summer_Sale_Reminder_PT"
    might be in GA4 as "Summer_Sale_Reminder" or similar.
    """
    if not campaign_name:
        return []
    
    # Split on common separators
    parts = re.split(r'[_\s-]+', campaign_name)
    
    # Filter out dates, prefixes, and short codes
    keywords = []
    for part in parts:
        part_lower = part.lower()
        # Skip dates, single letters, common prefixes
        if (len(part) > 2 and 
            not part.isdigit() and 
            not part_lower in ['p', 'em', 'pc', 'pt', 'd', 'hav', 'cz', 'id', 'bur', 'stf', 'ti']):
            keywords.append(part_lower)
    
    return keywords


def normalize_campaign_name_for_matching(campaign_name):
    """Normalize campaign name for matching against GA4 data."""
    if not campaign_name:
        return None
    
    # Remove common prefixes/suffixes
    name = campaign_name.strip()
    
    # Extract core name (remove date prefixes, brand codes, etc.)
    # This is a simple version - can be enhanced based on actual naming patterns
    return name.lower()


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


def build_campaign_matching_terms(campaign_data):
    """Build list of terms to match against GA4 campaign dimension."""
    campaign_name = campaign_data.get("name", "")
    braze_id = campaign_data.get("braze_id") or campaign_data.get("id", "")
    
    terms = []
    
    # Add full campaign name
    if campaign_name:
        terms.append(campaign_name.lower())
        # Add normalized version
        normalized = normalize_campaign_name_for_matching(campaign_name)
        if normalized and normalized != campaign_name.lower():
            terms.append(normalized)
    
    # Add Braze ID
    if braze_id:
        terms.append(braze_id.lower())
    
    # Add keywords
    keywords = extract_campaign_keywords(campaign_name)
    if len(keywords) >= 2:
        # Add combination of keywords as potential match
        terms.append(" ".join(keywords))
    
    return terms


def match_campaign_to_ga4_row(campaign_data, ga4_row, campaign_dimension_col):
    """Check if a GA4 row matches a campaign using exact name matching.

    Supports three match strategies (in order):
    1. Exact case-insensitive name match
    2. Klaviyo short ID match: GA4 stores "<name> (<klaviyo_message_id>)" for flow steps
    3. Braze ID substring match (legacy fallback)
    """
    # Handle case-insensitive column lookup (Snowflake returns uppercase)
    ga4_campaign_value = None
    for key in [campaign_dimension_col, campaign_dimension_col.upper(), campaign_dimension_col.lower()]:
        if key in ga4_row and ga4_row[key]:
            ga4_campaign_value = str(ga4_row[key]).strip()
            break

    if not ga4_campaign_value:
        return False

    campaign_name = campaign_data.get("name", "").strip()
    if not campaign_name:
        return False

    # 1. Exact match (case-insensitive)
    if campaign_name.lower() == ga4_campaign_value.lower():
        return True

    # 2. Klaviyo flow step match: GA4 appends " (<6-char-id>)" to the campaign name.
    #    The 6-char klaviyo_message_id is unique per message version, so matching on it
    #    is safe even when GA4 stores a different descriptive name than the YAML.
    #    Patterns seen in GA4:
    #      - "{yaml_name} ({id})"         e.g. "Email #1 Test #1 Aug 25 2022 VA (TdX6hj)"
    #      - "({id})"                     e.g. "(PFrNZQ)" — transactional, no description
    #      - "{different_name} ({id})"    e.g. "All orders (UyMKn4)" — Klaviyo renamed the flow
    klaviyo_msg_id = (campaign_data.get("klaviyo_message_id") or "").strip()
    if klaviyo_msg_id:
        id_suffix = f"({klaviyo_msg_id})"
        # Match any GA4 name that contains this ID in parentheses
        if id_suffix.lower() in ga4_campaign_value.lower():
            return True

    # 3. Braze ID substring match (legacy fallback)
    braze_id = campaign_data.get("braze_id") or campaign_data.get("id", "")
    if braze_id and braze_id.lower() in ga4_campaign_value.lower():
        return True

    return False


def query_campaign_metrics_batch(
    client: SnowflakeClient,
    campaigns: List[Dict[str, Any]],
    start_date: datetime,
    end_date: datetime,
    brand: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Query Snowflake for GA4 metrics for multiple campaigns in a batch.
    
    Returns a dictionary mapping campaign identifiers to metrics.
    """
    # Get configuration - use brand-specific table if available
    table = get_table_for_brand(brand) if brand else os.environ.get("SNOWFLAKE_GA4_TABLE", "TRAFFIC_SESSION_PERFORMANCE_DAILY")
    campaign_dimension = os.environ.get("SNOWFLAKE_CAMPAIGN_DIMENSION", "SESSIONCAMPAIGNNAME")
    brand_dimension = os.environ.get("SNOWFLAKE_BRAND_DIMENSION")
    date_column = os.environ.get("SNOWFLAKE_DATE_COLUMN", "DATE")
    sessions_column = os.environ.get("SNOWFLAKE_SESSIONS_COLUMN", "SESSIONS")
    purchases_column = os.environ.get("SNOWFLAKE_PURCHASES_COLUMN", "ECOMMERCEPURCHASES")
    revenue_column = os.environ.get("SNOWFLAKE_REVENUE_COLUMN", "TOTALREVENUE")
    # Use channel group (Email/SMS) for attribution—matches GA4 UI. Source/medium can misclassify.
    channel_group_col = os.environ.get("SNOWFLAKE_CHANNEL_GROUP_COLUMN") or _channel_group_column_for_brand(brand)
    
    # Build database.schema.table reference
    database = os.environ.get("SNOWFLAKE_DATABASE")
    # Use client's schema (which should be brand-specific)
    schema = client.schema
    full_table = f"{database}.{schema}.{table}"
    
    # Build WHERE conditions - use string formatting for safety
    # DATE column is VARCHAR, so we need to compare as string
    date_format = os.environ.get("SNOWFLAKE_DATE_FORMAT", "YYYYMMDD")
    if date_format == "YYYYMMDD":
        start_date_str = start_date.strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")
    else:
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")
    
    conditions = [
        f"{date_column} >= '{start_date_str}' AND {date_column} <= '{end_date_str}'",
    ]
    
    # Use channel group (Email/SMS) so attribution matches GA4 UI. Source/medium misclassifies SMS.
    if channel_group_col:
        cg = channel_group_col
        conditions.append(f"UPPER(TRIM({cg})) IN ('EMAIL', 'SMS')")
    
    # Add brand filter if available
    if brand and brand_dimension:
        conditions.append(f"{brand_dimension} = '{brand}'")
    
    # Derive channel from channel group (email/sms) for correct attribution per campaign
    channel_expr = (
        f"CASE WHEN UPPER(TRIM({channel_group_col})) = 'EMAIL' THEN 'email' "
        f"WHEN UPPER(TRIM({channel_group_col})) = 'SMS' THEN 'sms' END"
    )
    # Build query - separate rows per campaign per channel so we match email→email, sms→sms
    query = f"""
        SELECT 
            {campaign_dimension},
            {channel_expr} AS channel,
            SUM({sessions_column}) AS sessions,
            SUM({purchases_column}) AS purchases,
            SUM({revenue_column}) AS revenue
        FROM {full_table}
        WHERE {' AND '.join(conditions)}
            AND {campaign_dimension} IS NOT NULL
            AND {campaign_dimension} != ''
            AND {channel_expr} IS NOT NULL
        GROUP BY 1, 2
    """
    
    # No parameters needed - we're using string formatting (safe since dates are controlled)
    params = None
    
    try:
        rows = client.execute_query(query, params)
    except Exception as e:
        print(f"Error querying Snowflake: {e}")
        return {}
    
    # Match campaigns to GA4 rows; only use rows whose channel matches campaign channel
    campaign_metrics = {}
    
    for campaign_info in campaigns:
        campaign_data = campaign_info["data"]
        campaign_id = campaign_data.get("braze_id") or campaign_data.get("id") or campaign_info["file"].stem
        campaign_channel = (campaign_data.get("channel") or "").lower().strip()
        # Only attribute email/sms GA4 rows to email/sms campaigns
        if campaign_channel not in ("email", "sms"):
            campaign_metrics[campaign_id] = {"sessions": 0, "purchases": 0, "revenue": 0.0}
            continue
        
        matched_sessions = 0
        matched_purchases = 0
        matched_revenue = 0.0
        
        for row in rows:
            row_lower = {k.lower(): v for k, v in row.items()}
            row_channel = (row_lower.get("channel") or "").strip().lower()
            if row_channel != campaign_channel:
                continue
            if not match_campaign_to_ga4_row(campaign_data, row, campaign_dimension):
                continue
            matched_sessions += int(row_lower.get("sessions", 0) or 0)
            matched_purchases += int(row_lower.get("purchases", 0) or 0)
            matched_revenue += float(row_lower.get("revenue", 0) or 0.0)
        
        if matched_sessions > 0 or matched_purchases > 0 or matched_revenue > 0:
            campaign_metrics[campaign_id] = {
                "sessions": matched_sessions,
                "purchases": matched_purchases,
                "revenue": round(matched_revenue, 2),
            }
        else:
            campaign_metrics[campaign_id] = {
                "sessions": 0,
                "purchases": 0,
                "revenue": 0.0,
            }
    
    return campaign_metrics


def update_campaign_with_ga4(campaign_info, ga4_metrics, attribution_days, dry_run=False):
    """Update campaign YAML file with GA4 metrics."""
    filepath = campaign_info["file"]
    data = campaign_info["data"]
    
    # Ensure performance_summary exists
    if "performance_summary" not in data:
        data["performance_summary"] = {}
    
    # Add or update GA4 metrics (attributed to campaign channel: email or sms)
    data["performance_summary"]["ga4"] = {
        "sessions": ga4_metrics["sessions"],
        "purchases": ga4_metrics["purchases"],
        "revenue": ga4_metrics["revenue"],
        "attribution_window_days": attribution_days,
        "last_synced": datetime.now().isoformat(),
        "source": "snowflake",
        "channel": data.get("channel", ""),
    }
    
    if not dry_run:
        with open(filepath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return data["performance_summary"]["ga4"]


def process_campaigns_batch(
    campaigns: List[Dict[str, Any]],
    client: SnowflakeClient,
    default_attribution_days: int,
    brand: Optional[str] = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Process a batch of campaigns, querying Snowflake and updating YAML files.
    
    Returns (updated_count, no_match_count)
    """
    if not campaigns:
        return 0, 0
    
    # Group campaigns by date range for efficient querying
    # For now, we'll query all campaigns together and filter by date range in SQL
    # This is simpler and works well with daily aggregates
    
    # GA4 data coverage start — data before this date doesn't exist in Snowflake
    GA4_COVERAGE_START = datetime(2024, 7, 1)

    # Calculate date ranges for all campaigns
    campaign_date_ranges = []
    for campaign_info in campaigns:
        data = campaign_info["data"]
        dates = data.get("dates", {}) or {}

        # Klaviyo flows fire continuously — they have `dates.created` but no `first_sent`.
        # Don't require first_sent for flows; use the full GA4 coverage window instead.
        is_klaviyo_flow = (
            data.get("klaviyo_type") == "flow"
            or (data.get("braze_type") == "canvas_step" and data.get("klaviyo_message_id"))
        )

        first_sent = dates.get("first_sent")
        if not first_sent and not is_klaviyo_flow:
            continue

        try:
            now = datetime.now()

            if is_klaviyo_flow:
                start_date = GA4_COVERAGE_START
                end_date = now
                attribution_days = None  # not applicable — flows fire on user actions, not a single send
            else:
                if isinstance(first_sent, str):
                    first_sent_dt = datetime.fromisoformat(first_sent.replace("Z", "+00:00"))
                else:
                    first_sent_dt = first_sent

                if not isinstance(first_sent_dt, datetime):
                    continue

                attribution_days = determine_attribution_window(data, default_attribution_days)
                start_date = first_sent_dt.replace(tzinfo=None)
                end_date = start_date + timedelta(days=attribution_days)
                if end_date > now:
                    end_date = now

            campaign_date_ranges.append({
                "campaign_info": campaign_info,
                "start_date": start_date,
                "end_date": end_date,
                "attribution_days": attribution_days,
            })
        except Exception:
            continue
    
    if not campaign_date_ranges:
        return 0, 0
    
    # Find overall date range
    all_start = min(r["start_date"] for r in campaign_date_ranges)
    all_end = max(r["end_date"] for r in campaign_date_ranges)
    
    # Query all campaigns in one batch
    all_campaigns_for_query = [r["campaign_info"] for r in campaign_date_ranges]
    campaign_metrics = query_campaign_metrics_batch(
        client,
        all_campaigns_for_query,
        all_start,
        all_end,
        brand,
    )
    
    # Update each campaign
    updated_count = 0
    no_match_count = 0
    
    for date_range_info in campaign_date_ranges:
        campaign_info = date_range_info["campaign_info"]
        campaign_data = campaign_info["data"]
        campaign_id = campaign_data.get("braze_id") or campaign_data.get("id") or campaign_info["file"].stem
        
        metrics = campaign_metrics.get(campaign_id, {
            "sessions": 0,
            "purchases": 0,
            "revenue": 0.0,
        })
        
        attribution_days = date_range_info["attribution_days"]
        
        # Update campaign
        updated = update_campaign_with_ga4(
            campaign_info,
            metrics,
            attribution_days,
            dry_run=dry_run,
        )
        
        if updated:
            if metrics["sessions"] > 0 or metrics["purchases"] > 0 or metrics["revenue"] > 0:
                updated_count += 1
            else:
                no_match_count += 1
    
    return updated_count, no_match_count


def query_ga4_for_lifecycle_report(brand: str, start_date: datetime, end_date: datetime):
    """
    Query Snowflake GA4 data for lifecycle reporting.
    
    Returns a DataFrame with columns matching GA4 CSV format expected by combine_braze_ga4:
    - Session campaign (SESSIONCAMPAIGNNAME)
    - Event count (ECOMMERCEPURCHASES)
    - Total revenue (TOTALREVENUE)
    
    Args:
        brand: Brand code (CZ, ID, BUR)
        start_date: Start of report period
        end_date: End of report period
        
    Returns:
        pd.DataFrame with columns Session campaign, Event count, Total revenue
    """
    if pd is None:
        raise ImportError("pandas is required for query_ga4_for_lifecycle_report")

    schema = get_schema_for_brand(brand)
    if not schema:
        raise ValueError(f"No Snowflake schema configured for brand {brand}")

    table = get_table_for_brand(brand)
    campaign_dimension = os.environ.get("SNOWFLAKE_CAMPAIGN_DIMENSION", "SESSIONCAMPAIGNNAME")
    date_column = os.environ.get("SNOWFLAKE_DATE_COLUMN", "DATE")
    purchases_column = os.environ.get("SNOWFLAKE_PURCHASES_COLUMN", "ECOMMERCEPURCHASES")
    revenue_column = os.environ.get("SNOWFLAKE_REVENUE_COLUMN", "TOTALREVENUE")
    channel_group_col = os.environ.get("SNOWFLAKE_CHANNEL_GROUP_COLUMN") or _channel_group_column_for_brand(brand)
    database = os.environ.get("SNOWFLAKE_DATABASE")
    full_table = f"{database}.{schema}.{table}"

    date_format = os.environ.get("SNOWFLAKE_DATE_FORMAT", "YYYYMMDD")
    if date_format == "YYYYMMDD":
        start_date_str = start_date.strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")
    else:
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

    conditions = [
        f"{date_column} >= '{start_date_str}' AND {date_column} <= '{end_date_str}'",
        f"UPPER(TRIM({channel_group_col})) IN ('EMAIL', 'SMS')",
        f"{campaign_dimension} IS NOT NULL AND {campaign_dimension} != ''",
    ]

    query = f"""
        SELECT 
            {campaign_dimension} AS "Session campaign",
            SUM({purchases_column}) AS "Event count",
            SUM({revenue_column}) AS "Total revenue"
        FROM {full_table}
        WHERE {' AND '.join(conditions)}
        GROUP BY {campaign_dimension}
    """

    try:
        client = get_snowflake_client(schema=schema)
        rows = client.execute_query(query, None)
    except Exception as e:
        raise RuntimeError(f"Snowflake query failed for {brand}: {e}") from e

    df = pd.DataFrame(rows)
    # Normalize column names (Snowflake may return different casing)
    col_map = {}
    for c in df.columns:
        c_lower = str(c).strip().lower()
        if c_lower == "session campaign":
            col_map[c] = "Session campaign"
        elif c_lower == "event count":
            col_map[c] = "Event count"
        elif c_lower == "total revenue":
            col_map[c] = "Total revenue"
    if col_map:
        df = df.rename(columns=col_map)
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Import GA4 conversion metrics from Snowflake for campaigns"
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
    args = parser.parse_args()
    
    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return
    
    # Initialize base Snowflake connection config (will create brand-specific clients)
    print("Initializing Snowflake connection...")
    
    script_dir = Path(__file__).parent
    campaigns_dir = script_dir.parent / "campaigns"
    
    # Determine brands to process
    if args.all:
        brands = ["HAV", "CZ", "STF", "BUR", "ID", "TI"]
    else:
        brands = [normalize_brand(args.brand)]
    
    total_updated = 0
    total_no_match = 0
    
    for brand in brands:
        print(f"\n{'='*60}")
        print(f"Processing {brand}")
        print(f"{'='*60}")
        
        # Get schema for this brand
        schema = get_schema_for_brand(brand)
        if not schema:
            print(f"Warning: No schema configured for brand {brand}, skipping")
            continue
        
        print(f"Using schema: {schema}")
        
        # Create brand-specific Snowflake client
        try:
            client = get_snowflake_client(schema=schema)
            if not client.test_connection():
                print(f"Error: Failed to connect to Snowflake for {brand}")
                continue
            print("✓ Connected to Snowflake")
        except Exception as e:
            print(f"Error initializing Snowflake client for {brand}: {e}")
            continue
        
        try:
            # Load campaigns
            campaigns = load_campaigns(campaigns_dir, brand=brand, days_limit=args.days)
            print(f"Found {len(campaigns)} campaigns to process")
            
            if not campaigns:
                client.close()
                continue
            
            # Process in batch
            updated, no_match = process_campaigns_batch(
                campaigns,
                client,
                args.attribution_days,
                brand=brand,
                dry_run=args.dry_run,
            )
            
            print(f"\n{brand}: Updated {updated}, No Match {no_match}")
            total_updated += updated
            total_no_match += no_match
            
            # Print sample results
            if updated > 0:
                print("\nSample matches:")
                sample_count = 0
                for campaign_info in campaigns[:10]:  # Show first 10
                    campaign_data = campaign_info["data"]
                    campaign_id = campaign_data.get("braze_id") or campaign_data.get("id")
                    perf = campaign_data.get("performance_summary", {})
                    ga4 = perf.get("ga4", {})
                    if ga4.get("sessions", 0) > 0:
                        name = campaign_data.get("name", "")[:50]
                        sessions = ga4.get("sessions", 0)
                        purchases = ga4.get("purchases", 0)
                        revenue = ga4.get("revenue", 0)
                        print(f"  {name}: sessions={sessions}, purchases={purchases}, revenue=${revenue:.2f}")
                        sample_count += 1
                        if sample_count >= 5:
                            break
        finally:
            client.close()
    
    print(f"\n{'='*60}")
    print(f"TOTAL: Updated {total_updated}, No Match {total_no_match}")
    if args.dry_run:
        print("(Dry run - no files were modified)")


if __name__ == "__main__":
    main()

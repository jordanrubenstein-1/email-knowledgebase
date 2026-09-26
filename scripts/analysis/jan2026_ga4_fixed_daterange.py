#!/usr/bin/env python3
"""
January 2026: Top 5 by sessions and top 5 by revenue, per brand (GA4 brands only).
Split by ON-SALE vs OFF-SALE period.

GA4 data pulled for exact date range: 1/1/2026 - 1/31/2026 (no attribution window).
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from snowflake_client import get_snowflake_client

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"
REPORT_PATH = Path(__file__).parent.parent.parent / "reports" / "jan2026-ga4-top5-sessions-revenue.md"

GA4_BRANDS = ["ID", "BUR", "CZ"]
BRAND_NAMES = {"ID": "Interior Define", "BUR": "Burrow", "CZ": "The Citizenry"}
BRAND_SCHEMAS = {
    "ID": "LANDING_INTERIORDEFINE_GA4",
    "BUR": "LANDING_BURROW_GA4",
    "CZ": "LANDING_CITIZENRY_GA4",
}

# January 2026 sale periods
EOY_AND_YEAREND = [
    ("ID", "2026-01-01", "2026-01-06"),
    ("BUR", "2026-01-01", "2026-01-05"),
    ("CZ", "2026-01-01", "2026-01-04"),
]
WINTER_REFRESH_RETREAT = [
    ("ID", "2026-01-14", "2026-01-28"),
    ("BUR", "2026-01-15", "2026-01-27"),
    ("CZ", "2026-01-15", "2026-01-29"),
]
BUR_FLASH_SALE = [
    ("BUR", "2026-01-28", "2026-02-05"),
]


def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, AttributeError):
        return None


def date_in_range(d: datetime, start_str: str, end_str: str) -> bool:
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    day = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start <= day <= end


def is_during_sale(campaign: Dict[str, Any]) -> bool:
    brand = campaign.get("brand")
    if not brand:
        return False
    first_sent = (campaign.get("dates") or {}).get("first_sent")
    if not first_sent:
        return False
    d = parse_date(first_sent)
    if not d:
        return False
    for b, start, end in EOY_AND_YEAREND + WINTER_REFRESH_RETREAT + BUR_FLASH_SALE:
        if b == brand and date_in_range(d, start, end):
            return True
    return False


def get_name(c: Dict[str, Any]) -> str:
    return (c.get("name") or "").strip()


def load_jan2026_batch_email_for_brand(brand: str) -> List[Dict[str, Any]]:
    """Load January 2026 batch email campaigns for a specific brand."""
    campaigns = []
    for f in CAMPAIGNS_DIR.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(open(f))
        except Exception:
            continue
        if not data or data.get("channel") != "email":
            continue
        if data.get("braze_type") == "canvas_step":
            continue
        if data.get("brand") != brand:
            continue
        # Exclude TRADE emails for ID
        if brand == "ID" and "TRADE" in get_name(data):
            continue
        first_sent = (data.get("dates") or {}).get("first_sent")
        if not first_sent:
            continue
        d = parse_date(first_sent)
        if not d or d.year != 2026 or d.month != 1:
            continue
        perf = data.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 100:
            continue
        campaigns.append(data)
    return campaigns


def query_ga4_jan2026(brand: str) -> Dict[str, Dict[str, Any]]:
    """Query Snowflake for GA4 data from 1/1/2026 - 1/31/2026 for a brand.
    
    Returns dict mapping campaign name -> {sessions, purchases, revenue}
    """
    schema = BRAND_SCHEMAS.get(brand)
    if not schema:
        return {}
    
    database = os.environ.get("SNOWFLAKE_DATABASE")
    table = "TRAFFIC_SESSION_PERFORMANCE_DAILY"
    full_table = f"{database}.{schema}.{table}"
    
    # Query for exact date range 1/1-1/31/2026, Email channel only
    query = f"""
    SELECT 
        SESSIONCAMPAIGNNAME,
        SUM(SESSIONS) as sessions,
        SUM(ECOMMERCEPURCHASES) as purchases,
        SUM(TOTALREVENUE) as revenue
    FROM {full_table}
    WHERE DATE >= '20260101' AND DATE <= '20260131'
      AND UPPER(TRIM(SESSIONPRIMARYCHANNELGROUP)) = 'EMAIL'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND SESSIONCAMPAIGNNAME != ''
    GROUP BY SESSIONCAMPAIGNNAME
    """
    
    try:
        client = get_snowflake_client(schema=schema)
        rows = client.execute_query(query, None)
        client.close()
    except Exception as e:
        print(f"Error querying {brand}: {e}")
        return {}
    
    result = {}
    for row in rows:
        name = row.get('SESSIONCAMPAIGNNAME', '')
        result[name.lower()] = {
            'sessions': int(row.get('SESSIONS') or 0),
            'purchases': int(row.get('PURCHASES') or 0),
            'revenue': float(row.get('REVENUE') or 0),
        }
    return result


def match_campaigns_to_ga4(campaigns: List[Dict], ga4_data: Dict[str, Dict]) -> List[Dict]:
    """Match campaigns to GA4 data by exact name match."""
    for c in campaigns:
        name = get_name(c).lower()
        if name in ga4_data:
            c['_ga4'] = ga4_data[name]
        else:
            c['_ga4'] = {'sessions': 0, 'purchases': 0, 'revenue': 0}
    return campaigns


def get_sessions(c: Dict[str, Any]) -> int:
    return c.get('_ga4', {}).get('sessions', 0)


def get_revenue(c: Dict[str, Any]) -> float:
    return c.get('_ga4', {}).get('revenue', 0.0)


def top5_sessions(campaigns: List[Dict]) -> List[Dict]:
    return sorted(campaigns, key=get_sessions, reverse=True)[:5]


def top5_revenue(campaigns: List[Dict]) -> List[Dict]:
    return sorted(campaigns, key=get_revenue, reverse=True)[:5]


def main() -> None:
    lines = [
        "# January 2026 — Top 5 Sessions & Top 5 Revenue by Brand (GA4)",
        "",
        "**Brands with GA4 data:** Interior Define (ID), Burrow (BUR), The Citizenry (CZ).",
        "",
        "**GA4 date range:** 1/1/2026 - 1/31/2026 (exact, no attribution window).",
        "",
        "**On-sale:** EOY Sale Extension / Year-End Refresh + Winter Refresh / Winter Retreat + BUR Flash Sale.",
        "**Off-sale:** All other days in January 2026.",
        "",
        "---",
        "",
    ]

    for brand in GA4_BRANDS:
        label = BRAND_NAMES[brand]
        print(f"Processing {brand}...")
        
        # Load campaigns
        campaigns = load_jan2026_batch_email_for_brand(brand)
        print(f"  Found {len(campaigns)} campaigns")
        
        # Query GA4 data for 1/1-1/31
        ga4_data = query_ga4_jan2026(brand)
        print(f"  Found {len(ga4_data)} GA4 campaign records")
        
        # Match campaigns to GA4
        campaigns = match_campaigns_to_ga4(campaigns, ga4_data)
        
        # Split by sale period
        on_sale = [c for c in campaigns if is_during_sale(c)]
        off_sale = [c for c in campaigns if not is_during_sale(c)]
        
        lines.append(f"## {label} ({brand})")
        lines.append("")

        # On-sale
        lines.append("### On-sale period")
        lines.append("")
        lines.append("**Top 5 by sessions**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_sessions(on_sale):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")
        lines.append("**Top 5 by revenue**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_revenue(on_sale):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")

        # Off-sale
        lines.append("### Off-sale period")
        lines.append("")
        lines.append("**Top 5 by sessions**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_sessions(off_sale):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")
        lines.append("**Top 5 by revenue**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_revenue(off_sale):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()

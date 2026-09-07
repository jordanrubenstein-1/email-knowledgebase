#!/usr/bin/env python3
"""
Query emails that weren't sent during sale periods, sorted by revenue.

Supports any brand with GA4 data (default: ID). Use --brand to select e.g. BUR.

Usage:
    uv run python scripts/query_id_non_sale_revenue.py
    uv run python scripts/query_id_non_sale_revenue.py --brand BUR
"""

import argparse
import yaml
from pathlib import Path
import sys

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent))
from utils.sale_matcher import (
    load_sale_schedules,
    tag_campaigns_with_sales,
    filter_campaigns_by_sale,
)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

BRAND_DISPLAY = {
    "ID": "Interior Define",
    "BUR": "Burrow",
    "CZ": "The Citizenry",
    "HAV": "Havenly",
    "STF": "St. Frank",
    "TI": "The Inside",
}


def load_campaigns():
    """Load all campaign YAML files."""
    campaigns = []

    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if data:
                    data["_filename"] = yaml_file.name
                    campaigns.append(data)
        except Exception as e:
            print(f"Error loading {yaml_file.name}: {e}")

    return campaigns


def main():
    parser = argparse.ArgumentParser(
        description="Query non-sale emails by revenue (GA4). Default brand: ID."
    )
    parser.add_argument(
        "--brand",
        type=str,
        default="ID",
        help="Brand code (e.g. ID, BUR). Default: ID.",
    )
    args = parser.parse_args()
    brand = args.brand.strip().upper()
    display = BRAND_DISPLAY.get(brand, brand)

    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaigns")

    # Filter for selected brand, email channel, batch campaigns only
    brand_campaigns = [
        c for c in campaigns
        if c.get("brand") == brand
        and c.get("channel") == "email"
        and c.get("braze_type") != "canvas_step"  # Exclude triggered campaigns
    ]
    print(f"Found {len(brand_campaigns)} {brand} batch email campaigns")

    # Load sale schedules if available
    sale_schedules = load_sale_schedules()
    if sale_schedules:
        print(f"Loaded {len(sale_schedules)} sale periods")
        # Tag campaigns with sale context
        brand_campaigns = tag_campaigns_with_sales(brand_campaigns, sale_schedules)
        # Filter to campaigns NOT during sale periods
        non_sale_campaigns = filter_campaigns_by_sale(
            brand_campaigns, during_sale=False, sale_schedules=sale_schedules
        )
        print(f"Found {len(non_sale_campaigns)} {brand} campaigns NOT during sale periods")
    else:
        print(f"No sale schedules found - analyzing all {brand} campaigns")
        non_sale_campaigns = brand_campaigns
    
    # Filter to campaigns with revenue data and exclude obvious sale campaigns
    campaigns_with_revenue = []
    for c in non_sale_campaigns:
        # Skip campaigns that are explicitly sale_promo or reminder categories
        # (these would be during sales if schedules were loaded)
        category = c.get("category", "").lower()
        campaign_type = c.get("type", "").lower()
        name = c.get("name", "").lower()
        
        # Skip if it's clearly a sale campaign
        if category in ["sale_promo", "reminder"]:
            continue
        
        # Skip if name contains sale indicators (BFCM, sale, promo, etc.)
        sale_keywords = ["bfcm", "black friday", "cyber monday", "sale", "promo", "discount", 
                        "clearance", "labor day", "memorial day", "presidents day"]
        if any(keyword in name for keyword in sale_keywords):
            continue
        
        perf = c.get("performance_summary", {})
        # Use GA4 revenue instead of Braze total_revenue (Braze revenue is inflated 30-600x)
        # GA4 uses proper 7-day attribution window and is much more accurate
        ga4_data = perf.get("ga4", {})
        revenue = ga4_data.get("revenue", 0)
        
        # Only include campaigns with GA4 revenue data (more accurate)
        # Skip campaigns that only have Braze revenue as it's highly inflated
        if not revenue or revenue == 0:
            continue  # Skip campaigns without GA4 revenue
        
        use_braze_revenue = False
        
        if revenue and revenue > 0:
            campaigns_with_revenue.append({
                "campaign": c,
                "revenue": revenue,
                "revenue_source": "braze" if use_braze_revenue else "ga4",
                "sends": perf.get("total_sends", 0),
                "clicks": perf.get("total_clicks", 0),
                "opens": perf.get("total_opens", 0),
                "click_rate": perf.get("click_rate", 0),
                "open_rate": perf.get("open_rate", 0),
            })
    
    # Sort by revenue (descending)
    campaigns_with_revenue.sort(key=lambda x: x["revenue"], reverse=True)
    
    print(f"\nFound {len(campaigns_with_revenue)} non-sale campaigns with revenue data\n")
    print("=" * 100)
    print(f"Top {display} ({brand}) Non-Sale Emails by Revenue")
    print("=" * 100)
    print()
    
    # Display top 20
    for i, item in enumerate(campaigns_with_revenue[:20], 1):
        c = item["campaign"]
        name = c.get("name", "Unknown")
        dates = c.get("dates", {})
        send_date = dates.get("last_sent") or dates.get("first_sent", "Unknown")
        
        # Format send date
        if isinstance(send_date, str) and "T" in send_date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(send_date.replace("Z", "+00:00"))
                send_date = dt.strftime("%Y-%m-%d")
            except:
                pass
        
        print(f"{i}. {name}")
        print(f"   Revenue: ${item['revenue']:,.2f} (GA4, 7-day attribution)")
        print(f"   Sends: {item['sends']:,} | Opens: {item['opens']:,} ({item['open_rate']*100:.2f}%) | Clicks: {item['clicks']:,} ({item['click_rate']*100:.2f}%)")
        print(f"   Send Date: {send_date}")
        
        # Show category/type if available
        category = c.get("category")
        campaign_type = c.get("type")
        if category or campaign_type:
            print(f"   Category: {category or 'N/A'} | Type: {campaign_type or 'N/A'}")
        
        print()
    
    # Summary stats
    if campaigns_with_revenue:
        total_revenue = sum(item["revenue"] for item in campaigns_with_revenue)
        total_sends = sum(item["sends"] for item in campaigns_with_revenue)
        avg_revenue = total_revenue / len(campaigns_with_revenue)
        revenue_per_send = total_revenue / total_sends if total_sends > 0 else 0
        
        print("=" * 100)
        print("Summary Statistics")
        print("=" * 100)
        print(f"Total campaigns with revenue: {len(campaigns_with_revenue)}")
        print(f"Total revenue: ${total_revenue:,.2f}")
        print(f"Average revenue per campaign: ${avg_revenue:,.2f}")
        print(f"Revenue per send: ${revenue_per_send:.2f}")
        print(f"Total sends: {total_sends:,}")


if __name__ == "__main__":
    main()

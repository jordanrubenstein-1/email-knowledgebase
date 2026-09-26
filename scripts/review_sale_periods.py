#!/usr/bin/env python3
"""
Review sale periods to identify missing or miscategorized dates.

Checks for:
1. Campaigns that appear to be sale-related but aren't marked as during sale
2. Gaps in sale coverage
3. Potential date parsing issues
"""

import yaml
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).parent))
from utils.sale_matcher import load_sale_schedules, get_sale_context

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


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


def parse_campaign_date(date_str):
    """Parse campaign date to date string."""
    if not date_str:
        return None
    try:
        date_str = str(date_str).replace("Z", "+00:00")
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
        else:
            dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%d")
    except:
        return None


def main():
    print("Loading sale schedules...")
    sale_schedules = load_sale_schedules()
    print(f"Loaded {len(sale_schedules)} sale periods")
    
    print("\nLoading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} campaigns")
    
    # Filter to batch email campaigns
    batch_emails = [
        c for c in campaigns
        if c.get("channel") == "email"
        and c.get("braze_type") != "canvas_step"
        and c.get("sends")
    ]
    
    print(f"Found {len(batch_emails)} batch email campaigns\n")
    
    # Check for potential issues by brand
    issues_by_brand = defaultdict(list)
    
    for campaign in batch_emails:
        brand = campaign.get("brand")
        if not brand:
            continue
        
        name = campaign.get("name", "").lower()
        category = campaign.get("category", "").lower()
        
        # Get send date
        dates = campaign.get("dates", {})
        send_date_str = dates.get("last_sent") or dates.get("first_sent")
        send_date = parse_campaign_date(send_date_str)
        
        if not send_date:
            continue
        
        # Check sale context
        context = get_sale_context(campaign, sale_schedules)
        during_sale = context["during_sale"]
        
        # Flag potential issues
        sale_keywords = ["bfcm", "black friday", "cyber monday", "sale", "promo", "labor day", 
                        "memorial day", "presidents day", "clearance", "discount"]
        is_sale_like = any(kw in name for kw in sale_keywords) or category == "sale_promo"
        
        if is_sale_like and not during_sale:
            issues_by_brand[brand].append({
                "name": campaign.get("name"),
                "date": send_date,
                "category": campaign.get("category"),
                "reason": "Sale-like name/category but not during sale period"
            })
    
    # Report issues
    print("=" * 80)
    print("Sale Period Review - Potential Issues")
    print("=" * 80)
    print()
    
    if not issues_by_brand:
        print("No issues found! All sale-like campaigns are correctly categorized.")
        return
    
    for brand in sorted(issues_by_brand.keys()):
        issues = issues_by_brand[brand]
        print(f"\n{brand} - {len(issues)} potential issues:")
        print()
        
        # Group by date to find patterns
        by_date = defaultdict(list)
        for issue in issues:
            by_date[issue["date"]].append(issue)
        
        # Show issues sorted by date
        for date in sorted(by_date.keys()):
            date_issues = by_date[date]
            print(f"  {date}:")
            for issue in date_issues:
                print(f"    - {issue['name']}")
                print(f"      Category: {issue['category']}")
                print(f"      Reason: {issue['reason']}")
            print()
        
        # Check for date ranges that might be missing
        print(f"  Checking for missing sale periods...")
        brand_sales = [s for s in sale_schedules if s.get("brand") == brand]
        brand_sales.sort(key=lambda x: x.get("start_date", ""))
        
        # Find date ranges with many issues
        issue_dates = [parse_campaign_date(i["date"]) for i in issues if i["date"]]
        if issue_dates:
            min_issue_date = min(issue_dates)
            max_issue_date = max(issue_dates)
            print(f"  Issue date range: {min_issue_date} to {max_issue_date}")
            
            # Check if there are gaps in sale coverage
            print(f"  Brand sale periods in this range:")
            for sale in brand_sales:
                sale_start = sale.get("start_date", "")
                sale_end = sale.get("end_date", "")
                if sale_start and sale_end and min_issue_date <= sale_end <= max_issue_date:
                    print(f"    {sale.get('name')}: {sale_start} to {sale_end}")
    
    print("\n" + "=" * 80)
    print("Review complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()

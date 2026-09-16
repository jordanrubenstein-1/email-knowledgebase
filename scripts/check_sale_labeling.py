#!/usr/bin/env python3
"""
Check for campaigns that appear sale-related but are labeled as non-sale.

Looks for campaigns with sale keywords in name/category that aren't marked
as during a sale period.
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


def is_sale_like(campaign):
    """Check if campaign name/category suggests it's sale-related."""
    name = campaign.get("name", "").lower()
    category = campaign.get("category", "").lower()
    
    # Sale keywords
    sale_keywords = [
        "bfcm", "black friday", "cyber monday", "cyber week",
        "sale", "promo", "promotion", "discount", "clearance",
        "labor day", "memorial day", "presidents day", "president's day",
        "independence day", "july 4th", "4th of july", "fourth of july",
        "eoy", "end of year", "holiday", "thanksgiving",
        "friends and family", "f&f", "friends & family",
        "flash sale", "weekend sale", "summer sale", "winter sale",
        "spring sale", "fall sale", "autumn sale",
        "early access", "vip", "preview"
    ]
    
    # Check name
    name_has_keyword = any(kw in name for kw in sale_keywords)
    
    # Check category
    category_is_sale = category in ["sale_promo", "reminder"]  # reminders often for sales
    
    return name_has_keyword or category_is_sale


def main():
    print("Loading sale schedules...")
    sale_schedules = load_sale_schedules()
    print(f"Loaded {len(sale_schedules)} sale periods\n")
    
    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} campaigns\n")
    
    # Filter to batch email campaigns
    batch_emails = [
        c for c in campaigns
        if c.get("channel") == "email"
        and c.get("braze_type") != "canvas_step"
        and c.get("sends")
    ]
    
    print(f"Found {len(batch_emails)} batch email campaigns\n")
    
    # Check for potential mislabeling
    issues_by_brand = defaultdict(list)
    
    for campaign in batch_emails:
        brand = campaign.get("brand")
        if not brand:
            continue
        
        # Check if campaign looks sale-related
        if not is_sale_like(campaign):
            continue
        
        # Get send date
        dates = campaign.get("dates", {})
        send_date_str = dates.get("last_sent") or dates.get("first_sent")
        send_date = parse_campaign_date(send_date_str)
        
        if not send_date:
            continue
        
        # Check sale context
        context = get_sale_context(campaign, sale_schedules)
        during_sale = context["during_sale"]
        
        # If it looks sale-related but isn't marked as during sale, flag it
        if not during_sale:
            issues_by_brand[brand].append({
                "name": campaign.get("name"),
                "date": send_date,
                "category": campaign.get("category"),
                "filename": campaign.get("_filename"),
                "matching_sales": len(context.get("matching_sales", []))
            })
    
    # Report issues
    print("=" * 80)
    print("Sale Labeling Review - Potential Mislabeling")
    print("=" * 80)
    print()
    
    if not issues_by_brand:
        print("✓ No issues found! All sale-like campaigns are correctly labeled.")
        return
    
    total_issues = sum(len(issues) for issues in issues_by_brand.values())
    print(f"Found {total_issues} campaigns that appear sale-related but aren't marked as during sale:\n")
    
    for brand in sorted(issues_by_brand.keys()):
        issues = issues_by_brand[brand]
        print(f"\n{brand} - {len(issues)} potential issues:")
        print("-" * 80)
        
        # Group by date to find patterns
        by_date = defaultdict(list)
        for issue in issues:
            by_date[issue["date"]].append(issue)
        
        # Show issues sorted by date
        for date in sorted(by_date.keys()):
            date_issues = by_date[date]
            print(f"\n  {date} ({len(date_issues)} campaign(s)):")
            for issue in date_issues:
                print(f"    • {issue['name']}")
                print(f"      Category: {issue['category']}")
                print(f"      File: {issue['filename']}")
        
        # Check for date ranges that might be missing
        if len(issues) > 5:
            issue_dates = [parse_campaign_date(i["date"]) for i in issues if i["date"]]
            if issue_dates:
                min_issue_date = min(issue_dates)
                max_issue_date = max(issue_dates)
                print(f"\n  Date range with issues: {min_issue_date} to {max_issue_date}")
                
                # Check if there are gaps in sale coverage
                brand_sales = [s for s in sale_schedules if s.get("brand") == brand]
                brand_sales.sort(key=lambda x: x.get("start_date", ""))
                
                print(f"  Brand sale periods in this range:")
                for sale in brand_sales:
                    sale_start = sale.get("start_date", "")
                    sale_end = sale.get("end_date", "")
                    if sale_start and sale_end:
                        # Check if sale overlaps with issue date range
                        if (sale_start <= max_issue_date and sale_end >= min_issue_date):
                            print(f"    {sale.get('name')}: {sale_start} to {sale_end}")
    
    print("\n" + "=" * 80)
    print("Review complete!")
    print("=" * 80)
    print("\nNote: Some campaigns may be correctly labeled if:")
    print("  - They're pre-sale announcements (sent before sale starts)")
    print("  - They're post-sale reminders (sent after sale ends)")
    print("  - The sale period data is incomplete (especially for 2024)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Generate a summary report of sale labeling issues, focusing on the most critical cases.
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
            pass
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


def is_critical_sale_keyword(name_lower):
    """Check for critical sale keywords that should definitely be during sale."""
    critical_keywords = [
        "black friday", "bfcm", "cyber monday",
        "eoy", "end of year",
        "labor day",
        "memorial day",
        "presidents day", "president's day",
        "july 4th", "4th of july", "fourth of july", "independence day"
    ]
    return any(kw in name_lower for kw in critical_keywords)


def main():
    print("=" * 80)
    print("SALE LABELING REVIEW - CRITICAL ISSUES")
    print("=" * 80)
    print()
    
    sale_schedules = load_sale_schedules()
    campaigns = load_campaigns()
    
    batch_emails = [
        c for c in campaigns
        if c.get("channel") == "email"
        and c.get("braze_type") != "canvas_step"
        and c.get("sends")
    ]
    
    # Find critical issues
    critical_issues = []
    
    for campaign in batch_emails:
        brand = campaign.get("brand")
        if not brand:
            continue
        
        name = campaign.get("name", "").lower()
        category = campaign.get("category", "").lower()
        
        # Only flag critical sale keywords
        if not is_critical_sale_keyword(name):
            continue
        
        dates = campaign.get("dates", {})
        send_date_str = dates.get("last_sent") or dates.get("first_sent")
        send_date = parse_campaign_date(send_date_str)
        
        if not send_date:
            continue
        
        context = get_sale_context(campaign, sale_schedules)
        during_sale = context["during_sale"]
        
        if not during_sale:
            critical_issues.append({
                "brand": brand,
                "name": campaign.get("name"),
                "date": send_date,
                "category": category,
                "filename": campaign.get("_filename")
            })
    
    # Group by brand and date
    by_brand = defaultdict(list)
    for issue in critical_issues:
        by_brand[issue["brand"]].append(issue)
    
    print(f"Found {len(critical_issues)} campaigns with critical sale keywords not marked as during sale:\n")
    
    for brand in sorted(by_brand.keys()):
        issues = by_brand[brand]
        print(f"{brand}: {len(issues)} critical issues")
        print("-" * 80)
        
        # Group by keyword type
        black_friday = [i for i in issues if "black friday" in i["name"].lower() or "bfcm" in i["name"].lower()]
        eoy = [i for i in issues if "eoy" in i["name"].lower() or "end of year" in i["name"].lower()]
        labor_day = [i for i in issues if "labor day" in i["name"].lower()]
        other = [i for i in issues if i not in black_friday + eoy + labor_day]
        
        if black_friday:
            print(f"\n  Black Friday/BFCM ({len(black_friday)}):")
            for issue in sorted(black_friday, key=lambda x: x["date"]):
                print(f"    • {issue['date']}: {issue['name']}")
        
        if eoy:
            print(f"\n  End of Year ({len(eoy)}):")
            for issue in sorted(eoy, key=lambda x: x["date"]):
                print(f"    • {issue['date']}: {issue['name']}")
        
        if labor_day:
            print(f"\n  Labor Day ({len(labor_day)}):")
            for issue in sorted(labor_day, key=lambda x: x["date"]):
                print(f"    • {issue['date']}: {issue['name']}")
        
        if other:
            print(f"\n  Other ({len(other)}):")
            for issue in sorted(other, key=lambda x: x["date"])[:10]:  # Limit output
                print(f"    • {issue['date']}: {issue['name']}")
            if len(other) > 10:
                print(f"    ... and {len(other) - 10} more")
        
        print()
    
    print("=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)
    print()
    print("1. Review campaigns with 'Black Friday' in name - these should typically")
    print("   be during Black Friday sale periods (Nov 11-12 EA, Nov 13-14 Main Event)")
    print()
    print("2. Review campaigns with 'EOY' or 'End of Year' in name - check if")
    print("   End of Year sale periods are missing from sale schedules (especially 2024)")
    print()
    print("3. Review campaigns with 'Labor Day' in name - check if they're")
    print("   pre-announcements (sent before sale) or should be during sale")
    print()
    print("4. Many campaigns may be correctly labeled if they're:")
    print("   - Pre-sale announcements (sent 1-2 days before sale starts)")
    print("   - Post-sale reminders (sent after sale ends)")
    print("   - Early access for specific segments (may not match main sale period)")


if __name__ == "__main__":
    main()

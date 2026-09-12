#!/usr/bin/env python3
"""Quick script to count CZ campaigns by month for Oct-Dec 2025."""

import sys
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

# Import from analyze_sms_q4_2025
sys.path.insert(0, str(Path(__file__).parent))
from analyze_sms_q4_2025 import (
    parse_ga4_csv,
    get_sms_campaigns_from_braze,
    match_campaigns_to_ga4,
    fetch_braze_analytics_for_campaigns,
    extract_date_from_campaign_name,
    BRAND_CSV_MAPPING,
    START_DATE,
    END_DATE,
)

load_dotenv(Path(__file__).parent.parent / ".env")

def main():
    brand = "CZ"
    print(f"Analyzing {brand} campaigns by month (Oct-Dec 2025)...\n")
    
    # Parse CSV
    csv_path = BRAND_CSV_MAPPING[brand]
    ga4_data = parse_ga4_csv(csv_path, brand)
    print(f"Found {len(ga4_data)} campaigns in CSV")
    
    # Get Braze campaigns
    braze_campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
    print(f"Found {len(braze_campaigns)} SMS campaigns in Braze")
    
    # Match campaigns
    matched = match_campaigns_to_ga4(ga4_data, braze_campaigns)
    print(f"Matched {len(matched)} campaigns\n")
    
    # Fetch analytics
    fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
    
    # Count by month
    month_counts = defaultdict(int)
    campaigns_by_month = defaultdict(list)
    
    for campaign in matched:
        campaign_name = campaign.get('name', '')
        campaign_date = extract_date_from_campaign_name(campaign_name)
        month_name = None
        
        if campaign_date and campaign_date.year == 2025:
            if campaign_date.month == 10:
                month_name = 'October'
            elif campaign_date.month == 11:
                month_name = 'November'
            elif campaign_date.month == 12:
                month_name = 'December'
        elif not campaign_date:
            # Try created_at as fallback
            created_at = campaign.get('created_at')
            if created_at:
                try:
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        created_dt = created_at
                    if created_dt.year == 2025:
                        if created_dt.month == 10:
                            month_name = 'October'
                        elif created_dt.month == 11:
                            month_name = 'November'
                        elif created_dt.month == 12:
                            month_name = 'December'
                except Exception:
                    pass
        
        if month_name:
            month_counts[month_name] += 1
            campaigns_by_month[month_name].append(campaign_name)
    
    # Count undated campaigns
    undated_count = len(matched) - sum(month_counts.values())
    
    # Print results
    print("\nCZ Campaign Breakdown (Oct - Dec 2025):")
    print("=" * 50)
    for month in ['October', 'November', 'December']:
        count = month_counts[month]
        print(f"{month}: {count} campaigns")
    
    total = sum(month_counts.values())
    print(f"\nTotal dated: {total} campaigns")
    print(f"Undated (couldn't extract date): {undated_count} campaigns")
    print(f"Total matched: {len(matched)} campaigns")
    
    # Show sample campaigns for each month
    print("\nSample campaigns by month:")
    for month in ['October', 'November', 'December']:
        if campaigns_by_month[month]:
            print(f"\n{month} (showing first 5):")
            for name in sorted(campaigns_by_month[month])[:5]:
                print(f"  - {name}")

if __name__ == "__main__":
    main()


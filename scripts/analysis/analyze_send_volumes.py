#!/usr/bin/env python3
"""
Analyze email send volumes from campaign YAML files.

Calculates average sends per day/week/month/year across all brands
and broken down per brand.
"""

import os
import yaml
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any

def load_campaigns(campaigns_dir: Path) -> List[Dict[str, Any]]:
    """Load all campaign YAML files from the campaigns directory."""
    campaigns = []

    # Only load YAML files directly in campaigns/, not subdirectories
    yaml_files = list(campaigns_dir.glob("*.yaml"))

    print(f"Found {len(yaml_files)} YAML files in {campaigns_dir}")

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, 'r') as f:
                campaign = yaml.safe_load(f)
                if campaign:
                    campaigns.append(campaign)
        except Exception as e:
            print(f"Warning: Could not load {yaml_file.name}: {e}")

    return campaigns

def filter_email_campaigns(campaigns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter to only email campaigns with required fields."""
    email_campaigns = []

    for campaign in campaigns:
        # Check if it's an email campaign
        if campaign.get('channel') != 'email':
            continue

        # Check for required fields
        if not campaign.get('dates', {}).get('first_sent'):
            continue

        if not campaign.get('performance_summary', {}).get('total_sends'):
            continue

        email_campaigns.append(campaign)

    return email_campaigns

def parse_date(date_str: str) -> datetime:
    """Parse ISO 8601 datetime string."""
    # Handle timezone-aware datetime strings
    if '+' in date_str:
        date_str = date_str.split('+')[0]
    elif 'Z' in date_str:
        date_str = date_str.replace('Z', '')

    return datetime.fromisoformat(date_str)

def analyze_send_volumes(campaigns: List[Dict[str, Any]]) -> None:
    """Analyze and print send volume statistics."""

    # Overall stats
    total_sends = 0
    dates = []

    # Per-brand stats
    brand_sends = defaultdict(int)
    brand_dates = defaultdict(list)

    # Process all campaigns
    for campaign in campaigns:
        brand = campaign.get('brand', 'UNKNOWN')
        sends = campaign['performance_summary']['total_sends']
        date = parse_date(campaign['dates']['first_sent'])

        total_sends += sends
        dates.append(date)

        brand_sends[brand] += sends
        brand_dates[brand].append(date)

    # Calculate date range
    min_date = min(dates).date()
    max_date = max(dates).date()
    date_range_days = (max_date - min_date).days + 1
    date_range_weeks = date_range_days / 7
    date_range_months = date_range_days / 30.44  # Average month length
    date_range_years = date_range_days / 365.25

    # Print results
    print("\n" + "="*80)
    print("EMAIL SEND VOLUME ANALYSIS")
    print("="*80)

    print(f"\nDATE RANGE:")
    print(f"  First campaign: {min_date}")
    print(f"  Last campaign:  {max_date}")
    print(f"  Total days:     {date_range_days:,}")
    print(f"  Total weeks:    {date_range_weeks:.1f}")
    print(f"  Total months:   {date_range_months:.1f}")
    print(f"  Total years:    {date_range_years:.2f}")

    print(f"\nOVERALL STATISTICS:")
    print(f"  Total email campaigns: {len(campaigns):,}")
    print(f"  Total sends:           {total_sends:,}")

    print(f"\nAVERAGE SENDS (ALL BRANDS):")
    print(f"  Per day:   {total_sends / date_range_days:>15,.0f}")
    print(f"  Per week:  {total_sends / date_range_weeks:>15,.0f}")
    print(f"  Per month: {total_sends / date_range_months:>15,.0f}")
    print(f"  Per year:  {total_sends / date_range_years:>15,.0f}")

    # Per-brand breakdown
    print(f"\n{'='*80}")
    print("PER-BRAND BREAKDOWN")
    print("="*80)

    # Sort brands by total sends (descending)
    sorted_brands = sorted(brand_sends.items(), key=lambda x: x[1], reverse=True)

    for brand, sends in sorted_brands:
        brand_campaign_count = len(brand_dates[brand])
        brand_min_date = min(brand_dates[brand]).date()
        brand_max_date = max(brand_dates[brand]).date()
        brand_days = (brand_max_date - brand_min_date).days + 1
        brand_weeks = brand_days / 7
        brand_months = brand_days / 30.44
        brand_years = brand_days / 365.25

        print(f"\n{brand}:")
        print(f"  Date range:        {brand_min_date} to {brand_max_date} ({brand_days} days)")
        print(f"  Campaigns:         {brand_campaign_count:,}")
        print(f"  Total sends:       {sends:,}")
        print(f"  % of total:        {sends / total_sends * 100:.1f}%")
        print(f"  Avg per day:       {sends / brand_days:,.0f}")
        print(f"  Avg per week:      {sends / brand_weeks:,.0f}")
        print(f"  Avg per month:     {sends / brand_months:,.0f}")
        print(f"  Avg per year:      {sends / brand_years:,.0f}")

    print(f"\n{'='*80}\n")

def main():
    # Set up paths
    base_dir = Path("/Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase")
    campaigns_dir = base_dir / "campaigns"

    if not campaigns_dir.exists():
        print(f"Error: Campaigns directory not found: {campaigns_dir}")
        return

    # Load campaigns
    print("Loading campaigns...")
    campaigns = load_campaigns(campaigns_dir)
    print(f"Loaded {len(campaigns)} campaigns")

    # Filter to email campaigns
    email_campaigns = filter_email_campaigns(campaigns)
    print(f"Filtered to {len(email_campaigns)} email campaigns with required fields")

    if not email_campaigns:
        print("No email campaigns found!")
        return

    # Analyze
    analyze_send_volumes(email_campaigns)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Analyze SMS campaign data to identify insights and takeaways."""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from analyze_sms_q4_2025 import (
    parse_ga4_csv,
    get_sms_campaigns_from_braze,
    match_campaigns_to_ga4,
    fetch_braze_analytics_for_campaigns,
    filter_campaigns_with_extractable_dates,
    infer_brand_from_campaign_name,
    extract_date_from_campaign_name,
    format_currency,
    format_pct,
    BRAND_CSV_MAPPING,
    START_DATE,
    END_DATE,
)

load_dotenv(Path(__file__).parent.parent / ".env")


def analyze_insights():
    """Analyze SMS data for insights and takeaways."""
    print("SMS Campaign Analysis: Insights & Takeaways")
    print("=" * 70)
    
    # Collect data for all brands
    all_campaigns_by_brand = {}
    
    for brand in BRAND_CSV_MAPPING.keys():
        if brand == "TI":
            continue
        
        print(f"\nAnalyzing {brand}...")
        csv_path = BRAND_CSV_MAPPING[brand]
        ga4_data = parse_ga4_csv(csv_path, brand)
        braze_campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
        matched = match_campaigns_to_ga4(ga4_data, braze_campaigns)
        fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
        matched = filter_campaigns_with_extractable_dates(matched, START_DATE, END_DATE)
        brand_campaigns = [c for c in matched if infer_brand_from_campaign_name(c.get('name', '')) == brand]
        all_campaigns_by_brand[brand] = brand_campaigns
    
    print("\n" + "=" * 70)
    print("KEY INSIGHTS & TAKEAWAYS")
    print("=" * 70)
    
    # Insight 1: CTR vs Revenue correlation
    print("\n1. CTR vs REVENUE PERFORMANCE")
    print("-" * 70)
    for brand in sorted(all_campaigns_by_brand.keys()):
        campaigns = all_campaigns_by_brand[brand]
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0]
        
        if not campaigns_with_sends:
            continue
        
        # Sort by CTR and Revenue (top 5 to match report)
        top_ctr = sorted(campaigns_with_sends, key=lambda x: -x.get('braze_click_rate', 0))[:5]
        top_revenue = sorted(campaigns, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))[:5]
        
        # Check overlap
        top_ctr_names = {c['name'] for c in top_ctr}
        top_revenue_names = {c['name'] for c in top_revenue}
        overlap = len(top_ctr_names & top_revenue_names)
        
        avg_ctr_top_revenue = sum(c.get('braze_click_rate', 0) for c in top_revenue if c.get('braze_sends', 0) > 0) / max(len([c for c in top_revenue if c.get('braze_sends', 0) > 0]), 1)
        avg_ctr_all = sum(c.get('braze_click_rate', 0) for c in campaigns_with_sends) / len(campaigns_with_sends)
        
        print(f"\n{brand}:")
        print(f"  - Top 5 CTR campaigns overlap with top 5 revenue: {overlap}/5")
        print(f"  - Average CTR of top 5 revenue campaigns: {format_pct(avg_ctr_top_revenue)}")
        print(f"  - Average CTR across all campaigns: {format_pct(avg_ctr_all)}")
        
        if overlap == 0:
            print(f"  ⚠️  High CTR doesn't guarantee high revenue")
        elif overlap >= 3:
            print(f"  ✓  Strong correlation between CTR and revenue")
    
    # Insight 2: Campaign performance by type/theme
    print("\n\n2. CAMPAIGN TYPE PERFORMANCE")
    print("-" * 70)
    for brand in sorted(all_campaigns_by_brand.keys()):
        campaigns = all_campaigns_by_brand[brand]
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0]
        
        if not campaigns_with_sends:
            continue
        
        # Categorize by campaign name patterns
        categories = defaultdict(list)
        for c in campaigns_with_sends:
            name = c['name'].lower()
            if 'black friday' in name or 'bfcm' in name or 'cyber' in name:
                categories['Holiday/Sale'].append(c)
            elif 'launch' in name or 'new' in name:
                categories['Product Launch'].append(c)
            elif 'back in stock' in name:
                categories['Back in Stock'].append(c)
            elif 'reminder' in name:
                categories['Reminder'].append(c)
            elif 'sale' in name or 'clearance' in name:
                categories['Sale'].append(c)
            else:
                categories['Other'].append(c)
        
        print(f"\n{brand}:")
        
        # Calculate metrics for each category
        category_metrics = []
        for category, cats in categories.items():
            if cats:
                avg_ctr = sum(c.get('braze_click_rate', 0) for c in cats) / len(cats)
                avg_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in cats) / len(cats)
                category_metrics.append({
                    'category': category,
                    'count': len(cats),
                    'avg_ctr': avg_ctr,
                    'avg_revenue': avg_revenue,
                })
        
        # Sort by CTR (best performing first)
        category_metrics_sorted = sorted(category_metrics, key=lambda x: -x['avg_ctr'])
        
        # Print all categories
        for cat_metric in category_metrics_sorted:
            print(f"  {cat_metric['category']:20s} ({cat_metric['count']:2d} campaigns): "
                  f"Avg CTR: {format_pct(cat_metric['avg_ctr']):>8s}, Avg Revenue: {format_currency(cat_metric['avg_revenue'])}")
        
        # Identify best and 2nd best performing (by CTR)
        if len(category_metrics_sorted) >= 1:
            best = category_metrics_sorted[0]
            print(f"\n  Best performing: {best['category']} "
                  f"({format_pct(best['avg_ctr'])}, {format_currency(best['avg_revenue'])} avg revenue)")
        
        if len(category_metrics_sorted) >= 2:
            second_best = category_metrics_sorted[1]
            print(f"  2nd best performing: {second_best['category']} "
                  f"({format_pct(second_best['avg_ctr'])}, {format_currency(second_best['avg_revenue'])} avg revenue)")
    
    # Insight 3: Send volume vs performance
    print("\n\n3. SEND VOLUME vs PERFORMANCE")
    print("-" * 70)
    for brand in sorted(all_campaigns_by_brand.keys()):
        campaigns = all_campaigns_by_brand[brand]
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0]
        
        if len(campaigns_with_sends) < 5:
            continue
        
        # Split into high volume and low volume
        sorted_by_sends = sorted(campaigns_with_sends, key=lambda x: -x.get('braze_sends', 0))
        mid_point = len(sorted_by_sends) // 2
        high_volume = sorted_by_sends[:mid_point]
        low_volume = sorted_by_sends[mid_point:]
        
        avg_ctr_high = sum(c.get('braze_click_rate', 0) for c in high_volume) / len(high_volume)
        avg_ctr_low = sum(c.get('braze_click_rate', 0) for c in low_volume) / len(low_volume)
        avg_revenue_high = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in high_volume) / len(high_volume)
        avg_revenue_low = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in low_volume) / len(low_volume)
        
        print(f"\n{brand}:")
        print(f"  High volume campaigns ({len(high_volume)}): "
              f"Avg CTR: {format_pct(avg_ctr_high):>8s}, Avg Revenue: {format_currency(avg_revenue_high)}")
        print(f"  Low volume campaigns ({len(low_volume)}): "
              f"Avg CTR: {format_pct(avg_ctr_low):>8s}, Avg Revenue: {format_currency(avg_revenue_low)}")
    
    # Insight 4: Brand comparison
    print("\n\n4. BRAND COMPARISON")
    print("-" * 70)
    brand_metrics = {}
    for brand in sorted(all_campaigns_by_brand.keys()):
        campaigns = all_campaigns_by_brand[brand]
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0]
        
        if not campaigns_with_sends:
            continue
        
        total_sends = sum(c.get('braze_sends', 0) for c in campaigns_with_sends)
        total_clicks = sum(c.get('braze_clicks', 0) for c in campaigns_with_sends)
        total_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in campaigns)
        avg_ctr = (total_clicks / total_sends) if total_sends > 0 else 0
        revenue_per_m = (total_revenue / total_sends * 1_000_000) if total_sends > 0 else 0
        
        brand_metrics[brand] = {
            'campaigns': len(campaigns_with_sends),
            'avg_ctr': avg_ctr,
            'total_revenue': total_revenue,
            'revenue_per_m': revenue_per_m,
            'total_sends': total_sends,
        }
    
    print("\nOverall Performance:")
    print(f"{'Brand':<6} {'Campaigns':<12} {'Avg CTR':<12} {'Total Revenue':<15} {'Revenue/$1M Sends':<20}")
    for brand in sorted(brand_metrics.keys()):
        m = brand_metrics[brand]
        print(f"{brand:<6} {m['campaigns']:<12} {format_pct(m['avg_ctr']):<12} "
              f"{format_currency(m['total_revenue']):<15} {format_currency(m['revenue_per_m'])}")
    
    # Insight 5: Best and worst performers
    print("\n\n5. BEST & WORST PERFORMERS")
    print("-" * 70)
    
    all_campaigns = []
    for campaigns in all_campaigns_by_brand.values():
        all_campaigns.extend(campaigns)
    
    campaigns_with_sends = [c for c in all_campaigns if c.get('braze_sends', 0) > 0]
    campaigns_sorted_ctr = sorted(campaigns_with_sends, key=lambda x: -x.get('braze_click_rate', 0))
    campaigns_sorted_revenue = sorted(all_campaigns, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))
    
    print("\nTop 3 by CTR (all brands):")
    for idx, c in enumerate(campaigns_sorted_ctr[:3], 1):
        brand = infer_brand_from_campaign_name(c['name'])
        print(f"  {idx}. [{brand}] {c['name'][:55]}")
        print(f"     CTR: {format_pct(c.get('braze_click_rate', 0))}, "
              f"Revenue: {format_currency(c.get('ga4_metrics', {}).get('revenue', 0))}, "
              f"Sends: {c.get('braze_sends', 0):,}")
    
    print("\nTop 3 by Revenue (all brands):")
    for idx, c in enumerate(campaigns_sorted_revenue[:3], 1):
        brand = infer_brand_from_campaign_name(c['name'])
        ctr = format_pct(c.get('braze_click_rate', 0)) if c.get('braze_sends', 0) > 0 else "N/A"
        print(f"  {idx}. [{brand}] {c['name'][:55]}")
        print(f"     Revenue: {format_currency(c.get('ga4_metrics', {}).get('revenue', 0))}, "
              f"CTR: {ctr}, Sends: {c.get('braze_sends', 0):,}")
    
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    
    # Generate recommendations
    print("\n• Focus on campaigns that balance CTR and revenue - high CTR alone doesn't guarantee revenue")
    print("• Test different campaign types to identify what resonates with each brand's audience")
    print("• Monitor send volume vs performance - smaller, targeted sends may perform better")
    print("• Analyze top revenue performers to understand what messaging/content drives conversions")
    print("• Review bottom CTR performers to identify messaging or targeting improvements")


if __name__ == "__main__":
    analyze_insights()


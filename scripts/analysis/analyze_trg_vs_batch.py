#!/usr/bin/env python3
"""Analyze TRG_ (triggered/drip) vs P_ (batch/blast) SMS campaign performance."""

import sys
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from analyze_sms_q4_2025 import (
    get_sms_campaigns_from_braze,
    match_campaigns_to_ga4,
    fetch_braze_analytics_for_campaigns,
    infer_brand_from_campaign_name,
    extract_date_from_campaign_name,
    format_currency,
    format_pct,
    format_number,
    normalize_campaign_name,
    BRAND_CSV_MAPPING,
    BRAND_BRAZE_MAPPING,
    START_DATE,
    END_DATE,
    braze_request_brand,
)
from parse_ga4_csv_including_trg import parse_ga4_csv_including_trg as parse_ga4_csv
from import_braze import get_canvases, get_canvas_details, get_canvas_analytics, get_config, init_config

load_dotenv(Path(__file__).parent.parent / ".env")


def is_sms_campaign(campaign_name):
    """Check if campaign name indicates SMS channel (including TRG_)."""
    if not campaign_name:
        return False
    name_upper = campaign_name.upper()
    name_lower = campaign_name.lower()
    
    import re
    if (re.search(r'_SMS[_\-]|_SMS$', name_upper) or
            name_upper.startswith("SMS_") or 
            name_upper.endswith("_SMS") or
            " SMS" in name_upper or
            "-SMS-" in name_upper or
            name_upper.endswith("-SMS") or
            "_SMS_" in name_upper):
        return True
    
    if "_sms-" in name_lower or "-sms-" in name_lower:
        return True
    
    return False


def get_all_sms_campaigns_from_braze(brand, max_pages=20):
    """Fetch ALL SMS campaigns from Braze (including TRG_)."""
    campaigns = []
    
    params = {
        "page": 0,
        "include_archived": False,
        "sort_direction": "desc"
    }
    
    while params["page"] < max_pages:
        from analyze_sms_q4_2025 import braze_request_brand
        data = braze_request_brand(brand, "campaigns/list", params)
        if not data or "campaigns" not in data:
            break
        
        batch = data["campaigns"]
        if not batch:
            break
        
        for campaign in batch:
            campaign_name = campaign.get('name', '')
            
            # Include ALL SMS campaigns (don't filter out TRG_)
            if not is_sms_campaign(campaign_name):
                continue
            
            campaigns.append({
                'id': campaign['id'],
                'name': campaign_name,
                'created_at': campaign.get("created_at"),
                'tags': campaign.get('tags', []),
            })
        
        params["page"] += 1
    
    return campaigns


def match_campaigns_with_all_types(ga4_data, braze_campaigns):
    """Match GA4 data to Braze campaigns (including TRG_)."""
    matched = []
    
    from analyze_sms_q4_2025 import normalize_campaign_name
    
    # Create normalized lookup for Braze campaigns
    braze_lookup = {}
    for braze_campaign in braze_campaigns:
        campaign_name = braze_campaign.get('name', '')
        normalized = normalize_campaign_name(campaign_name)
        braze_lookup[normalized] = braze_campaign
    
    # Match from GA4 data
    for ga4_name, ga4_metrics in ga4_data.items():
        normalized_ga4 = normalize_campaign_name(ga4_name)
        
        # Try exact match first
        if normalized_ga4 in braze_lookup:
            braze_campaign = braze_lookup[normalized_ga4]
            matched.append({
                'braze_id': braze_campaign['id'],
                'name': ga4_name,
                'braze_name': braze_campaign.get('name', ''),
                'ga4_name': ga4_name,
                'ga4_metrics': ga4_metrics.copy(),
                'created_at': braze_campaign.get('created_at'),
            })
        else:
            # Try partial matching
            best_match = None
            best_score = 0
            
            for braze_normalized, braze_campaign in braze_lookup.items():
                if normalized_ga4 in braze_normalized or braze_normalized in normalized_ga4:
                    overlap = len(set(normalized_ga4.split()) & set(braze_normalized.split()))
                    total = len(set(normalized_ga4.split()) | set(braze_normalized.split()))
                    score = overlap / total if total > 0 else 0
                    
                    if score > best_score and score > 0.6:
                        best_score = score
                        best_match = braze_campaign
            
            if best_match:
                matched.append({
                    'braze_id': best_match['id'],
                    'name': ga4_name,
                    'braze_name': best_match.get('name', ''),
                    'ga4_name': ga4_name,
                    'ga4_metrics': ga4_metrics.copy(),
                    'created_at': best_match.get('created_at'),
                })
    
    return matched


def categorize_campaign_type(campaign_name):
    """Categorize campaign as TRG_ or P_ or Other."""
    if not campaign_name:
        return "Other"
    name_upper = campaign_name.upper()
    
    if name_upper.startswith("TRG_"):
        return "TRG_"
    elif name_upper.startswith("P_"):
        return "P_"
    else:
        return "Other"


def extract_touchpoint_number(campaign_name):
    """Extract touchpoint number (T1, T2, T3, etc.) from campaign name.
    Returns the number as int, or None if not found.
    Examples: TRG_SMS_2025_07_ID_Welcome_T1_EOY -> 1
              TRG_SMS_2025_07_ID_Welcome_T3_V1 -> 3
    """
    if not campaign_name:
        return None
    
    # Look for pattern like _T1_, _T2_, _T1_EOY, _T3_V1, etc.
    match = re.search(r'_T(\d+)[_\-]', campaign_name.upper())
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    return None


def extract_canvas_type(campaign_name):
    """Extract canvas type from campaign name (Welcome, Cart Abandon, etc.).
    Returns normalized type string or None.
    """
    if not campaign_name:
        return None
    
    name_upper = campaign_name.upper()
    
    # Common patterns
    if 'WELCOME' in name_upper:
        return 'Welcome'
    elif 'CART' in name_upper and 'ABANDON' in name_upper:
        return 'Cart Abandon'
    elif 'BROWSE' in name_upper and 'ABANDON' in name_upper:
        return 'Browse Abandon'
    elif 'PRODUCT' in name_upper and 'BROWSE' in name_upper:
        return 'Product Browse'
    elif 'POST' in name_upper and 'PURCHASE' in name_upper:
        return 'Post Purchase'
    elif 'PBA' in name_upper or ('POST' in name_upper and 'BUY' in name_upper):
        return 'Post Purchase'
    elif 'WAITLIST' in name_upper:
        return 'Waitlist'
    
    return None


def combine_touchpoint_steps(campaigns):
    """Combine campaigns that have the same brand, canvas type, and touchpoint number.
    Returns list of combined campaigns with aggregated metrics.
    """
    # Group by (brand, canvas_type, touchpoint)
    groups = defaultdict(list)
    
    for campaign in campaigns:
        brand = campaign.get('brand')
        canvas_type = extract_canvas_type(campaign.get('name', ''))
        touchpoint = extract_touchpoint_number(campaign.get('name', ''))
        
        if brand and canvas_type and touchpoint:
            key = (brand, canvas_type, touchpoint)
            groups[key].append(campaign)
        else:
            # Keep ungroupable campaigns as-is (use name as key)
            groups[(campaign.get('name', 'other'), None, None)].append(campaign)
    
    combined = []
    for key, group_campaigns in groups.items():
        if len(group_campaigns) == 1:
            combined.append(group_campaigns[0])
        else:
            # Combine metrics
            combined_campaign = {
                'name': f"{key[0]} {key[1]} T{key[2]} (Combined)",
                'brand': key[0],
                'canvas_type': key[1],
                'touchpoint': key[2],
                'ga4_metrics': {
                    'revenue': sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in group_campaigns),
                    'sessions': sum(c.get('ga4_metrics', {}).get('sessions', 0) for c in group_campaigns),
                    'purchases': sum(c.get('ga4_metrics', {}).get('purchases', 0) for c in group_campaigns),
                },
                'braze_sends': sum(c.get('braze_sends', 0) for c in group_campaigns),
                'braze_clicks': sum(c.get('braze_clicks', 0) for c in group_campaigns),
                'braze_click_rate': 0,  # Will calculate below
                'original_campaigns': [c.get('name') for c in group_campaigns],
            }
            
            # Calculate combined CTR
            if combined_campaign['braze_sends'] > 0:
                combined_campaign['braze_click_rate'] = combined_campaign['braze_clicks'] / combined_campaign['braze_sends']
            
            combined.append(combined_campaign)
    
    return combined


def fetch_canvas_analytics_for_trg_campaigns(trg_campaigns, brand):
    """Fetch Canvas analytics for TRG_ campaigns by matching to Canvas steps.
    
    TRG_ campaigns are Canvas steps, so we need to:
    1. Get all Canvas flows
    2. Match TRG_ campaign names to Canvas step names
    3. Get Canvas analytics with step breakdown
    4. Extract send/click data for matching steps
    """
    print(f"  Fetching Canvas data for {len(trg_campaigns)} TRG_ campaigns...")
    
    # Initialize config for brand
    init_config(BRAND_BRAZE_MAPPING.get(brand, brand))
    
    # Get all Canvas flows
    try:
        all_canvases = get_canvases()
    except Exception as e:
        print(f"    Error fetching canvases: {e}")
        return
    
    # Create lookup of TRG_ campaign names (normalized)
    trg_lookup = {}
    for campaign in trg_campaigns:
        name = campaign.get('name', '')
        normalized = normalize_campaign_name(name)
        trg_lookup[normalized] = campaign
    
    # Match TRG_ campaigns to Canvas steps
    matched_count = 0
    
    for canvas in all_canvases:
        canvas_id = canvas.get('id')
        canvas_name = canvas.get('name', '')
        
        # Get canvas details to see steps
        try:
            details = get_canvas_details(canvas_id)
            if not details:
                continue
            
            # Check if canvas has SMS channel
            channels = details.get('channels', [])
            if 'sms' not in channels:
                continue
            
            # Get canvas steps
            steps = details.get('steps', [])
            for step in steps:
                if step.get('type') != 'message':
                    continue
                
                step_name = step.get('name', '')
                normalized_step = normalize_campaign_name(step_name)
                
                # Check if this step matches a TRG_ campaign
                if normalized_step in trg_lookup:
                    campaign = trg_lookup[normalized_step]
                    
                    # Get canvas analytics
                    try:
                        analytics = get_canvas_analytics(canvas_id, START_DATE, END_DATE)
                        if analytics and 'data' in analytics:
                            step_id = step.get('id')
                            
                            # Extract send/click data from step_stats
                            total_sends = 0
                            total_clicks = 0
                            
                            stats_list = analytics['data'].get('stats', [])
                            for day_data in stats_list:
                                step_stats = day_data.get('step_stats', {})
                                step_data = step_stats.get(step_id, {})
                                messages = step_data.get('messages', {})
                                
                                for channel, variants in messages.items():
                                    if channel == 'sms' and isinstance(variants, list):
                                        for variant in variants:
                                            total_sends += variant.get('sent', 0)
                                            total_clicks += variant.get('clicks', 0)
                            
                            if total_sends > 0:
                                campaign['braze_sends'] = total_sends
                                campaign['braze_clicks'] = total_clicks
                                campaign['braze_click_rate'] = total_clicks / total_sends
                                campaign['canvas_id'] = canvas_id
                                matched_count += 1
                    except Exception as e:
                        # Skip if analytics fetch fails
                        pass
        except Exception as e:
            # Skip if canvas details fetch fails
            continue
    
    print(f"    Matched {matched_count} TRG_ campaigns to Canvas steps with analytics")


def analyze_trg_vs_batch():
    """Analyze TRG_ vs P_ campaign performance."""
    print("TRG_ (Triggered/Drip) vs P_ (Batch/Blast) SMS Analysis")
    print("=" * 70)
    
    # Collect data for all brands
    all_campaigns = []
    
    for brand in BRAND_CSV_MAPPING.keys():
        if brand == "TI":
            continue
        
        print(f"\nProcessing {brand}...")
        csv_path = BRAND_CSV_MAPPING[brand]
        ga4_data = parse_ga4_csv(csv_path, brand)
        print(f"  Found {len(ga4_data)} campaigns in CSV (including TRG_)")
        
        # Get ALL SMS campaigns from Braze
        braze_campaigns = get_all_sms_campaigns_from_braze(brand, max_pages=20)
        print(f"  Found {len(braze_campaigns)} SMS campaigns in Braze")
        
        # Separate TRG_ and P_ campaigns from GA4 data
        ga4_trg = {name: metrics for name, metrics in ga4_data.items() if categorize_campaign_type(name) == 'TRG_'}
        ga4_p = {name: metrics for name, metrics in ga4_data.items() if categorize_campaign_type(name) == 'P_'}
        
        print(f"    TRG_ campaigns in CSV: {len(ga4_trg)}")
        print(f"    P_ campaigns in CSV: {len(ga4_p)}")
        
        # For P_ campaigns, use the same matching logic as generate_p_campaigns_report.py
        # Import the matching function from analyze_sms_q4_2025
        from analyze_sms_q4_2025 import match_campaigns_to_ga4 as match_p_campaigns
        
        # Match P_ campaigns with Braze data (same as generate_p_campaigns_report.py)
        matched_p_with_braze = match_p_campaigns(ga4_p, braze_campaigns)
        fetch_braze_analytics_for_campaigns(matched_p_with_braze, brand, START_DATE, END_DATE)
        
        # Match TRG_ campaigns (they won't match to Braze campaigns, they're Canvas steps)
        # Use match_campaigns_with_all_types for TRG_ since they might have different naming
        matched_trg_with_braze = match_campaigns_with_all_types(ga4_trg, braze_campaigns)
        
        # Include campaigns from GA4 - use the same approach as generate_p_campaigns_report.py
        # For P_ campaigns, only include those that were matched (same as generate_p_campaigns_report.py)
        all_campaigns_from_ga4 = []
        matched_p_names = {c['name'] for c in matched_p_with_braze}
        matched_trg_names = {c['name'] for c in matched_trg_with_braze}
        
        # Add P_ campaigns (only matched ones, same as generate_p_campaigns_report.py)
        for campaign in matched_p_with_braze:
            all_campaigns_from_ga4.append(campaign)
        
        # Add TRG_ campaigns
        for ga4_name, ga4_metrics in ga4_trg.items():
            if ga4_name in matched_trg_names:
                matched_campaign = next(c for c in matched_trg_with_braze if c['name'] == ga4_name)
                all_campaigns_from_ga4.append(matched_campaign)
            else:
                # TRG_ campaign without Braze match (it's a Canvas step)
                all_campaigns_from_ga4.append({
                    'braze_id': None,
                    'name': ga4_name,
                    'braze_name': None,
                    'ga4_name': ga4_name,
                    'ga4_metrics': ga4_metrics.copy(),
                    'created_at': None,
                    'braze_sends': 0,  # Will be filled from Canvas analytics
                    'braze_clicks': 0,
                    'braze_click_rate': 0,
                })
        
        # Separate campaigns by type
        matched_p = [c for c in all_campaigns_from_ga4 if categorize_campaign_type(c['name']) == 'P_']
        matched_trg = [c for c in all_campaigns_from_ga4 if categorize_campaign_type(c['name']) == 'TRG_']
        
        print(f"    P_ campaigns: {len(matched_p)} (with Braze data)")
        print(f"    TRG_ campaigns: {len(matched_trg)} (will fetch Canvas analytics)")
        
        # Fetch Canvas analytics for TRG_ campaigns
        if matched_trg:
            fetch_canvas_analytics_for_trg_campaigns(matched_trg, brand)
        
        # Add metadata
        for campaign in all_campaigns_from_ga4:
            campaign['brand'] = infer_brand_from_campaign_name(campaign['name'])
            campaign['campaign_type'] = categorize_campaign_type(campaign['name'])
        
        all_campaigns.extend(all_campaigns_from_ga4)
        print(f"  Total campaigns analyzed: {len(all_campaigns_from_ga4)} ({len(matched_p)} P_, {len(matched_trg)} TRG_)")
    
    print(f"\nTotal campaigns analyzed: {len(all_campaigns)}")
    
    # Filter campaigns to only include those with extractable dates in the date range
    # (same filtering as in analyze_sms_q4_2025.py)
    all_campaigns_filtered = []
    for campaign in all_campaigns:
        campaign_name = campaign.get('name', '')
        campaign_date = extract_date_from_campaign_name(campaign_name)
        if campaign_date and START_DATE <= campaign_date <= END_DATE:
            all_campaigns_filtered.append(campaign)
        elif not campaign_date:
            # Keep campaigns without dates for now, but we'll filter them out
            pass
    
    # Categorize by type (using filtered campaigns)
    trg_campaigns = [c for c in all_campaigns_filtered if c['campaign_type'] == 'TRG_']
    p_campaigns = [c for c in all_campaigns_filtered if c['campaign_type'] == 'P_']
    other_campaigns = [c for c in all_campaigns_filtered if c['campaign_type'] == 'Other']
    
    print(f"\nAfter filtering by extractable dates:")
    print(f"  TRG_ campaigns: {len(trg_campaigns)}")
    print(f"  P_ campaigns: {len(p_campaigns)}")
    print(f"  Other campaigns: {len(other_campaigns)}")
    
    print(f"\nCampaign breakdown by type:")
    print(f"  TRG_ campaigns: {len(trg_campaigns)}")
    print(f"  P_ campaigns: {len(p_campaigns)}")
    print(f"  Other campaigns: {len(other_campaigns)}")
    
    # Overall comparison
    print("\n" + "=" * 70)
    print("OVERALL PERFORMANCE: TRG_ vs P_")
    print("=" * 70)
    
    def calculate_metrics(campaigns):
        if not campaigns:
            return None
        
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0]
        total_sends = sum(c.get('braze_sends', 0) for c in campaigns_with_sends)
        total_clicks = sum(c.get('braze_clicks', 0) for c in campaigns_with_sends)
        total_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in campaigns)
        total_sessions = sum(c.get('ga4_metrics', {}).get('sessions', 0) for c in campaigns)
        total_purchases = sum(c.get('ga4_metrics', {}).get('purchases', 0) for c in campaigns)
        
        avg_ctr = (total_clicks / total_sends) if total_sends > 0 else 0
        revenue_per_m = (total_revenue / total_sends * 1_000_000) if total_sends > 0 else 0
        avg_revenue = total_revenue / len(campaigns) if campaigns else 0
        avg_sessions = total_sessions / len(campaigns) if campaigns else 0
        
        return {
            'count': len(campaigns),
            'count_with_sends': len(campaigns_with_sends),
            'total_sends': total_sends,
            'total_clicks': total_clicks,
            'total_revenue': total_revenue,
            'total_sessions': total_sessions,
            'total_purchases': total_purchases,
            'avg_ctr': avg_ctr,
            'revenue_per_m': revenue_per_m,
            'avg_revenue': avg_revenue,
            'avg_sessions': avg_sessions,
        }
    
    trg_metrics = calculate_metrics(trg_campaigns)
    p_metrics = calculate_metrics(p_campaigns)
    
    # Print metrics table (handle case where TRG_ might be None)
    if p_metrics:
        print(f"\n{'Metric':<30} {'TRG_ (Canvas Steps)':<25} {'P_ (Campaigns)':<25} {'Note':<30}")
        print("-" * 110)
        # Handle TRG_ metrics (might be None if no TRG_ campaigns)
        trg_count = trg_metrics['count'] if trg_metrics else 0
        trg_revenue_str = format_currency(trg_metrics['total_revenue']) if trg_metrics else '$0'
        trg_avg_revenue_str = format_currency(trg_metrics['avg_revenue']) if trg_metrics else '$0'
        trg_sessions_str = f"{trg_metrics['total_sessions']:,}" if trg_metrics else '0'
        trg_avg_sessions_str = f"{trg_metrics['avg_sessions']:.1f}" if trg_metrics else '0.0'
        trg_purchases = trg_metrics['total_purchases'] if trg_metrics else 0
        trg_sends_str = f"{trg_metrics['total_sends']:,}" if trg_metrics else '0'
        trg_clicks_str = format_number(trg_metrics['total_clicks']) if trg_metrics else '0'
        trg_ctr_str = format_pct(trg_metrics['avg_ctr']) if trg_metrics and trg_metrics['total_sends'] > 0 else '0.00%'
        trg_rev_per_m_str = format_currency(trg_metrics['revenue_per_m']) if trg_metrics and trg_metrics['total_sends'] > 0 else 'N/A'
        
        print(f"{'Campaigns':<30} {trg_count:<25} {p_metrics['count']:<25}")
        print(f"{'Total Revenue':<30} {trg_revenue_str:<25} {format_currency(p_metrics['total_revenue']):<25}")
        print(f"{'Avg Revenue/Campaign':<30} {trg_avg_revenue_str:<25} {format_currency(p_metrics['avg_revenue']):<25}")
        print(f"{'Total Sessions':<30} {trg_sessions_str:<25} {p_metrics['total_sessions']:<25,}")
        print(f"{'Avg Sessions/Campaign':<30} {trg_avg_sessions_str:<25} {p_metrics['avg_sessions']:<25.1f}")
        print(f"{'Total Purchases':<30} {trg_purchases:<25} {p_metrics['total_purchases']:<25}")
        print(f"{'Total Sends':<30} {trg_sends_str:<25} {format_number(p_metrics['total_sends']):<25}")
        print(f"{'Total Clicks':<30} {trg_clicks_str:<25} {format_number(p_metrics['total_clicks']):<25}")
        if trg_metrics and trg_metrics['total_sends'] > 0:
            ctr_diff = abs(trg_metrics['avg_ctr'] - p_metrics['avg_ctr'])
            ctr_higher = 'higher' if trg_metrics['avg_ctr'] > p_metrics['avg_ctr'] else 'lower'
            print(f"{'Average CTR':<30} {trg_ctr_str:<25} {format_pct(p_metrics['avg_ctr']):<25} "
                  f"{format_pct(ctr_diff)} {ctr_higher}")
        else:
            print(f"{'Average CTR':<30} {trg_ctr_str:<25} {format_pct(p_metrics['avg_ctr']):<25}")
        print(f"{'Revenue per $1M Sends':<30} {trg_rev_per_m_str:<25} {format_currency(p_metrics['revenue_per_m']):<25}")
    
    # By brand comparison
    print("\n" + "=" * 70)
    print("PERFORMANCE BY BRAND: TRG_ vs P_")
    print("=" * 70)
    
    for brand in sorted(set(c['brand'] for c in all_campaigns if c['brand'])):
        brand_trg = [c for c in trg_campaigns if c['brand'] == brand]
        brand_p = [c for c in p_campaigns if c['brand'] == brand]
        
        brand_trg_metrics = calculate_metrics(brand_trg)
        brand_p_metrics = calculate_metrics(brand_p)
        
        if brand_trg_metrics or brand_p_metrics:
            print(f"\n{brand}:")
            if brand_trg_metrics:
                trg_ctr_str = format_pct(brand_trg_metrics['avg_ctr']) if brand_trg_metrics['total_sends'] > 0 else "N/A"
                print(f"  TRG_ ({brand_trg_metrics['count']} Canvas steps): "
                      f"CTR: {trg_ctr_str}, "
                      f"Revenue: {format_currency(brand_trg_metrics['total_revenue'])}, "
                      f"Avg Revenue/Step: {format_currency(brand_trg_metrics['avg_revenue'])}, "
                      f"Sessions: {brand_trg_metrics['total_sessions']:,}, "
                      f"Sends: {format_number(brand_trg_metrics['total_sends'])}")
            else:
                print(f"  TRG_: No campaigns")
            
            if brand_p_metrics:
                print(f"  P_ ({brand_p_metrics['count']} campaigns): "
                      f"CTR: {format_pct(brand_p_metrics['avg_ctr'])}, "
                      f"Revenue: {format_currency(brand_p_metrics['total_revenue'])}, "
                      f"Avg Revenue/Campaign: {format_currency(brand_p_metrics['avg_revenue'])}, "
                      f"Sessions: {brand_p_metrics['total_sessions']:,}, "
                      f"Sends: {format_number(brand_p_metrics['total_sends'])}")
            else:
                print(f"  P_: No campaigns")
    
    # Side-by-side comparison: Top 5 TRG_ vs Top 5 P_ by CTR, by brand (ALL BRANDS)
    print("\n" + "=" * 70)
    print("TOP 5 TRG_ vs TOP 5 P_ BY CTR - SIDE-BY-SIDE BY BRAND")
    print("=" * 70)
    
    all_brands = sorted(set(c['brand'] for c in all_campaigns if c['brand']))
    
    for brand in all_brands:
        brand_trg = [c for c in trg_campaigns if c['brand'] == brand]
        brand_p = [c for c in p_campaigns if c['brand'] == brand]
        
        if not brand_trg and not brand_p:
            continue
        
        print(f"\n{brand}:")
        print("-" * 140)
        
        # Combine TRG_ by touchpoint
        combined_trg = combine_touchpoint_steps(brand_trg)
        trg_with_ctr = [c for c in combined_trg if c.get('braze_sends', 0) > 0]
        top5_trg = sorted(trg_with_ctr, key=lambda x: -x.get('braze_click_rate', 0))[:5]
        
        # Get top 5 P_ by CTR
        p_with_ctr = [c for c in brand_p if c.get('braze_sends', 0) > 0]
        top5_p = sorted(p_with_ctr, key=lambda x: -x.get('braze_click_rate', 0))[:5]
        
        # Calculate overall P_ metrics
        brand_p_metrics = calculate_metrics(brand_p)
        
        # Print side-by-side header
        print(f"{'Rank':<6} {'TRG_ (Triggered/Drip)':<50} {'CTR':<12} {'Rank':<6} {'P_ (Batch/Blast)':<50} {'CTR':<12}")
        print("-" * 140)
        
        max_rows = max(len(top5_trg), len(top5_p))
        for i in range(max_rows):
            trg_row = ""
            p_row = ""
            
            if i < len(top5_trg):
                trg_c = top5_trg[i]
                trg_name = trg_c.get('name', '')[:49]
                if trg_c.get('original_campaigns'):
                    trg_name = f"{trg_name} ({len(trg_c['original_campaigns'])} versions)"
                trg_row = f"{i+1:<6} {trg_name:<50} {format_pct(trg_c.get('braze_click_rate', 0)):<12}"
            else:
                trg_row = f"{'':<6} {'':<50} {'':<12}"
            
            if i < len(top5_p):
                p_c = top5_p[i]
                p_name = p_c.get('name', '')[:49]
                p_row = f"{i+1:<6} {p_name:<50} {format_pct(p_c.get('braze_click_rate', 0)):<12}"
            else:
                p_row = f"{'':<6} {'':<50} {'':<12}"
            
            print(f"{trg_row} {p_row}")
        
        # Print overall P_ metrics
        if brand_p_metrics:
            print(f"\n  P_ Overall: {brand_p_metrics['count']} campaigns, "
                  f"Avg CTR: {format_pct(brand_p_metrics['avg_ctr'])}, "
                  f"Avg Revenue/Campaign: {format_currency(brand_p_metrics['avg_revenue'])}, "
                  f"Total Sends: {format_number(brand_p_metrics['total_sends'])}")
        
        if not top5_trg:
            print(f"{'No TRG_ campaigns with CTR data':<68} ", end="")
        if not top5_p:
            print(f"{'No P_ campaigns with CTR data':<68}")
    
    # Volume vs Revenue analysis for P_ campaigns
    print("\n" + "=" * 70)
    print("P_ CAMPAIGNS: VOLUME VS REVENUE ANALYSIS (BW, ID, CZ, SF)")
    print("=" * 70)
    
    volume_analysis_brands = ['BW', 'ID', 'CZ', 'SF']
    
    for brand in volume_analysis_brands:
        brand_p = [c for c in p_campaigns if c['brand'] == brand]
        if not brand_p:
            continue
        
        # Calculate median sends to split into low/high volume
        sends_list = [c.get('braze_sends', 0) for c in brand_p if c.get('braze_sends', 0) > 0]
        if not sends_list:
            continue
        
        import statistics
        median_sends = statistics.median(sends_list)
        
        low_volume = [c for c in brand_p if 0 < c.get('braze_sends', 0) < median_sends]
        high_volume = [c for c in brand_p if c.get('braze_sends', 0) >= median_sends]
        
        low_vol_revenue = [c.get('ga4_metrics', {}).get('revenue', 0) for c in low_volume]
        high_vol_revenue = [c.get('ga4_metrics', {}).get('revenue', 0) for c in high_volume]
        
        avg_low_vol = sum(low_vol_revenue) / len(low_vol_revenue) if low_vol_revenue else 0
        avg_high_vol = sum(high_vol_revenue) / len(high_vol_revenue) if high_vol_revenue else 0
        
        print(f"\n{brand}:")
        print(f"  Median sends threshold: {median_sends:,.0f}")
        print(f"  Low volume campaigns (< {median_sends:,.0f} sends): {len(low_volume)} campaigns")
        print(f"    Avg revenue: {format_currency(avg_low_vol)}")
        print(f"  High volume campaigns (>= {median_sends:,.0f} sends): {len(high_volume)} campaigns")
        print(f"    Avg revenue: {format_currency(avg_high_vol)}")
        
        # Calculate revenue per send for comparison
        low_vol_rev_per_send = []
        high_vol_rev_per_send = []
        for c in low_volume:
            sends = c.get('braze_sends', 0)
            revenue = c.get('ga4_metrics', {}).get('revenue', 0)
            if sends > 0:
                low_vol_rev_per_send.append(revenue / sends)
        for c in high_volume:
            sends = c.get('braze_sends', 0)
            revenue = c.get('ga4_metrics', {}).get('revenue', 0)
            if sends > 0:
                high_vol_rev_per_send.append(revenue / sends)
        
        avg_low_vol_rev_per_send = sum(low_vol_rev_per_send) / len(low_vol_rev_per_send) if low_vol_rev_per_send else 0
        avg_high_vol_rev_per_send = sum(high_vol_rev_per_send) / len(high_vol_rev_per_send) if high_vol_rev_per_send else 0
        
        if avg_low_vol > avg_high_vol:
            print(f"  ✓ Pattern confirmed: Low volume = {format_currency(avg_low_vol)} vs High volume = {format_currency(avg_high_vol)}")
            print(f"  All low-volume campaigns by revenue:")
            low_vol_sorted = sorted(low_volume, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))
            for idx, c in enumerate(low_vol_sorted, 1):
                revenue = c.get('ga4_metrics', {}).get('revenue', 0)
                sends = c.get('braze_sends', 0)
                print(f"    {idx}. {c.get('name', '')[:70]}: {format_currency(revenue)} ({sends:,} sends)")
            print(f"  All high-volume campaigns by revenue:")
            high_vol_sorted = sorted(high_volume, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))
            for idx, c in enumerate(high_vol_sorted, 1):
                revenue = c.get('ga4_metrics', {}).get('revenue', 0)
                sends = c.get('braze_sends', 0)
                print(f"    {idx}. {c.get('name', '')[:70]}: {format_currency(revenue)} ({sends:,} sends)")
        elif avg_low_vol_rev_per_send > avg_high_vol_rev_per_send:
            print(f"  ⚠ Pattern partially confirmed (by revenue per send):")
            print(f"    Low volume avg revenue: {format_currency(avg_low_vol)} vs High volume: {format_currency(avg_high_vol)}")
            print(f"    Low volume revenue per send: ${avg_low_vol_rev_per_send:.4f} vs High volume: ${avg_high_vol_rev_per_send:.4f}")
            print(f"  Top low-volume campaigns by revenue per send:")
            low_vol_with_rev = [c for c in low_volume if c.get('braze_sends', 0) > 0 and c.get('ga4_metrics', {}).get('revenue', 0) > 0]
            low_vol_sorted = sorted(low_vol_with_rev, key=lambda x: -(x.get('ga4_metrics', {}).get('revenue', 0) / x.get('braze_sends', 1)))[:5]
            for idx, c in enumerate(low_vol_sorted, 1):
                revenue = c.get('ga4_metrics', {}).get('revenue', 0)
                sends = c.get('braze_sends', 0)
                rev_per_send = revenue / sends if sends > 0 else 0
                print(f"    {idx}. {c.get('name', '')[:60]}: {format_currency(revenue)} ({sends:,} sends, ${rev_per_send:.4f}/send)")
        else:
            print(f"  ✗ Pattern not confirmed: Low volume = {format_currency(avg_low_vol)} vs High volume = {format_currency(avg_high_vol)}")
            print(f"    Low volume revenue per send: ${avg_low_vol_rev_per_send:.4f} vs High volume: ${avg_high_vol_rev_per_send:.4f}")
    
    # Volume vs CTR analysis for P_ campaigns
    print("\n" + "=" * 70)
    print("P_ CAMPAIGNS: VOLUME VS CTR ANALYSIS (ID, CZ, SF)")
    print("=" * 70)
    
    for brand in volume_analysis_brands:
        brand_p = [c for c in p_campaigns if c['brand'] == brand]
        if not brand_p:
            continue
        
        # Calculate median sends to split into low/high volume
        sends_list = [c.get('braze_sends', 0) for c in brand_p if c.get('braze_sends', 0) > 0]
        if not sends_list:
            continue
        
        import statistics
        median_sends = statistics.median(sends_list)
        
        low_volume = [c for c in brand_p if 0 < c.get('braze_sends', 0) < median_sends]
        high_volume = [c for c in brand_p if c.get('braze_sends', 0) >= median_sends]
        
        # Calculate average CTR for each group
        low_vol_ctr = []
        high_vol_ctr = []
        for c in low_volume:
            ctr = c.get('braze_click_rate', 0)
            if c.get('braze_sends', 0) > 0:
                low_vol_ctr.append(ctr)
        for c in high_volume:
            ctr = c.get('braze_click_rate', 0)
            if c.get('braze_sends', 0) > 0:
                high_vol_ctr.append(ctr)
        
        avg_low_vol_ctr = sum(low_vol_ctr) / len(low_vol_ctr) if low_vol_ctr else 0
        avg_high_vol_ctr = sum(high_vol_ctr) / len(high_vol_ctr) if high_vol_ctr else 0
        
        print(f"\n{brand}:")
        print(f"  Median sends threshold: {median_sends:,.0f}")
        print(f"  Low volume campaigns (< {median_sends:,.0f} sends): {len(low_volume)} campaigns")
        print(f"    Avg CTR: {format_pct(avg_low_vol_ctr)}")
        print(f"  High volume campaigns (>= {median_sends:,.0f} sends): {len(high_volume)} campaigns")
        print(f"    Avg CTR: {format_pct(avg_high_vol_ctr)}")
        
        if avg_low_vol_ctr > avg_high_vol_ctr:
            print(f"  ✓ Pattern confirmed: Low volume = {format_pct(avg_low_vol_ctr)} vs High volume = {format_pct(avg_high_vol_ctr)}")
            print(f"  Top low-volume campaigns by CTR:")
            low_vol_with_sends = [c for c in low_volume if c.get('braze_sends', 0) > 0]
            low_vol_sorted = sorted(low_vol_with_sends, key=lambda x: -x.get('braze_click_rate', 0))[:5]
            for idx, c in enumerate(low_vol_sorted, 1):
                ctr = c.get('braze_click_rate', 0)
                sends = c.get('braze_sends', 0)
                print(f"    {idx}. {c.get('name', '')[:60]}: {format_pct(ctr)} ({sends:,} sends)")
        else:
            print(f"  ✗ Pattern not confirmed: Low volume = {format_pct(avg_low_vol_ctr)} vs High volume = {format_pct(avg_high_vol_ctr)}")
    
    # Top TRG_ campaigns by brand
    print("\n" + "=" * 70)
    print("TOP TRG_ CAMPAIGNS BY BRAND")
    print("=" * 70)
    
    if trg_campaigns:
        # Group by brand
        trg_by_brand = defaultdict(list)
        for c in trg_campaigns:
            brand = c.get('brand')
            if brand:
                trg_by_brand[brand].append(c)
        
        for brand in sorted(trg_by_brand.keys()):
            brand_trg = trg_by_brand[brand]
            
            # Combine by touchpoint
            combined_trg = combine_touchpoint_steps(brand_trg)
            
            print(f"\n{brand} - Top TRG_ Campaigns (Combined by Touchpoint):")
            print(f"{'Rank':<6} {'Campaign/Touchpoint':<50} {'CTR':<12} {'Revenue':<15} {'Sessions':<12} {'Sends':<12}")
            print("-" * 110)
            
            # Sort by CTR (if available) or revenue
            combined_with_ctr = [c for c in combined_trg if c.get('braze_sends', 0) > 0]
            if combined_with_ctr:
                sorted_trg = sorted(combined_with_ctr, key=lambda x: -x.get('braze_click_rate', 0))[:10]
                for idx, c in enumerate(sorted_trg, 1):
                    name = c.get('name', '')[:49]
                    # Show original campaign names if combined
                    if c.get('original_campaigns'):
                        name = f"{name} ({len(c['original_campaigns'])} versions)"
                    print(f"{idx:<6} {name:<50} {format_pct(c.get('braze_click_rate', 0)):<12} "
                          f"{format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                          f"{c.get('ga4_metrics', {}).get('sessions', 0):<12} "
                          f"{c.get('braze_sends', 0):<12,}")
            else:
                # Sort by revenue if no CTR data
                sorted_trg = sorted(combined_trg, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))[:10]
                for idx, c in enumerate(sorted_trg, 1):
                    name = c.get('name', '')[:49]
                    if c.get('original_campaigns'):
                        name = f"{name} ({len(c['original_campaigns'])} versions)"
                    print(f"{idx:<6} {name:<50} {'N/A':<12} "
                          f"{format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                          f"{c.get('ga4_metrics', {}).get('sessions', 0):<12} {'N/A':<12}")
    
    # Top TRG_ campaigns by CTR (with meaningful volume)
    print("\n" + "=" * 70)
    print("TOP TRG_ CAMPAIGNS BY CTR (MEANINGFUL VOLUME: 30+ SENDS)")
    print("=" * 70)
    
    if trg_campaigns:
        # Combine all TRG_ campaigns by touchpoint
        combined_all = combine_touchpoint_steps(trg_campaigns)
        
        # Filter to campaigns with meaningful volume (30+ sends)
        combined_with_volume = [c for c in combined_all if c.get('braze_sends', 0) >= 30]
        
        if combined_with_volume:
            # Sort by CTR
            sorted_by_ctr = sorted(combined_with_volume, key=lambda x: -x.get('braze_click_rate', 0))[:10]
            
            print(f"\nTop 10 TRG_ Campaigns/Touchpoints by CTR (30+ sends):")
            print(f"{'Rank':<6} {'Brand':<6} {'Campaign/Touchpoint':<50} {'CTR':<12} {'Sends':<12} {'Revenue':<15} {'Sessions':<12}")
            print("-" * 120)
            for idx, c in enumerate(sorted_by_ctr, 1):
                name = c.get('name', '')[:49]
                if c.get('original_campaigns'):
                    name = f"{name} ({len(c['original_campaigns'])} versions)"
                print(f"{idx:<6} {c.get('brand', 'N/A'):<6} {name:<50} {format_pct(c.get('braze_click_rate', 0)):<12} "
                      f"{c.get('braze_sends', 0):<12,} {format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                      f"{c.get('ga4_metrics', {}).get('sessions', 0):<12}")
        else:
            print("\nNo TRG_ campaigns with 30+ sends found")
    
    # Top TRG_ steps by revenue (combined by touchpoint)
    print("\n" + "=" * 70)
    print("TOP TRG_ STEPS BY REVENUE (COMBINED BY TOUCHPOINT)")
    print("=" * 70)
    
    if trg_campaigns:
        # Combine all TRG_ campaigns by touchpoint
        combined_all = combine_touchpoint_steps(trg_campaigns)
        
        # Sort by revenue
        sorted_by_revenue = sorted(combined_all, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))[:10]
        
        print(f"\nTop 10 TRG_ Steps/Touchpoints by Revenue:")
        print(f"{'Rank':<6} {'Brand':<6} {'Step/Touchpoint':<50} {'Revenue':<15} {'CTR':<12} {'Sends':<12} {'Sessions':<12}")
        print("-" * 120)
        for idx, c in enumerate(sorted_by_revenue, 1):
            name = c.get('name', '')[:49]
            if c.get('original_campaigns'):
                name = f"{name} ({len(c['original_campaigns'])} versions)"
            ctr_str = format_pct(c.get('braze_click_rate', 0)) if c.get('braze_sends', 0) > 0 else 'N/A'
            print(f"{idx:<6} {c.get('brand', 'N/A'):<6} {name:<50} "
                  f"{format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                  f"{ctr_str:<12} {c.get('braze_sends', 0):<12,} "
                  f"{c.get('ga4_metrics', {}).get('sessions', 0):<12}")
    
    # Top TRG_ campaigns overall (individual, not combined)
    print("\n" + "=" * 70)
    print("TOP TRG_ CAMPAIGNS OVERALL BY REVENUE (INDIVIDUAL CAMPAIGNS)")
    print("=" * 70)
    
    if trg_campaigns:
        # Top by Revenue (individual campaigns, not combined)
        trg_sorted_revenue = sorted(trg_campaigns, key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0))[:10]
        print("\nTop 10 TRG_ Campaigns by Revenue:")
        print(f"{'Rank':<6} {'Brand':<6} {'Campaign Name':<55} {'Revenue':<15} {'Sessions':<12} {'Purchases':<12}")
        print("-" * 110)
        for idx, c in enumerate(trg_sorted_revenue, 1):
            print(f"{idx:<6} {c['brand']:<6} {c['name'][:54]:<55} "
                  f"{format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                  f"{c.get('ga4_metrics', {}).get('sessions', 0):<12} "
                  f"{c.get('ga4_metrics', {}).get('purchases', 0):<12}")
        
        # Top by Sessions
        trg_sorted_sessions = sorted(trg_campaigns, key=lambda x: -x.get('ga4_metrics', {}).get('sessions', 0))[:10]
        print("\nTop 10 TRG_ Campaigns by Sessions:")
        print(f"{'Rank':<6} {'Brand':<6} {'Campaign Name':<55} {'Sessions':<12} {'Revenue':<15} {'Purchases':<12}")
        print("-" * 110)
        for idx, c in enumerate(trg_sorted_sessions, 1):
            print(f"{idx:<6} {c['brand']:<6} {c['name'][:54]:<55} "
                  f"{c.get('ga4_metrics', {}).get('sessions', 0):<12} "
                  f"{format_currency(c.get('ga4_metrics', {}).get('revenue', 0)):<15} "
                  f"{c.get('ga4_metrics', {}).get('purchases', 0):<12}")
    else:
        print("\nNo TRG_ campaigns found")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    analyze_trg_vs_batch()


#!/usr/bin/env python3
"""
Analyze Havenly AI email campaign performance
Compare December 2025 vs other months
"""

import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import statistics

campaigns_dir = Path(__file__).parent.parent.parent / "campaigns"

def load_ai_campaigns():
    """Load all Havenly AI-related campaigns"""
    ai_campaigns = []
    
    for yaml_file in campaigns_dir.glob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                campaign = yaml.safe_load(f)
                
            if not campaign:
                continue
                
            # Check if it's Havenly and AI-related
            brand = campaign.get('brand', '')
            name = campaign.get('name', '').upper()
            
            if brand == 'HAV' and 'AI' in name:
                # Get first sent date
                dates = campaign.get('dates', {})
                first_sent = dates.get('first_sent')
                
                if first_sent:
                    try:
                        sent_date = datetime.fromisoformat(first_sent.replace('Z', '+00:00'))
                        campaign['_sent_date'] = sent_date
                        campaign['_sent_month'] = sent_date.strftime('%Y-%m')
                        ai_campaigns.append(campaign)
                    except:
                        pass
        except Exception as e:
            continue
    
    return sorted(ai_campaigns, key=lambda x: x.get('_sent_date', datetime.min))

def analyze_performance(campaigns):
    """Analyze performance metrics"""
    results = defaultdict(list)
    
    for campaign in campaigns:
        month = campaign.get('_sent_month', 'unknown')
        perf = campaign.get('performance_summary', {})
        
        if perf:
            results[month].append({
                'name': campaign.get('name', ''),
                'date': campaign.get('_sent_date'),
                'open_rate': perf.get('open_rate', 0),
                'click_rate': perf.get('click_rate', 0),
                'total_sends': perf.get('total_sends', 0),
                'total_opens': perf.get('total_opens', 0),
                'total_clicks': perf.get('total_clicks', 0),
            })
    
    return results

def calculate_stats(campaigns_list):
    """Calculate aggregate statistics"""
    if not campaigns_list:
        return None
    
    open_rates = [c['open_rate'] for c in campaigns_list if c['open_rate']]
    click_rates = [c['click_rate'] for c in campaigns_list if c['click_rate']]
    total_sends = sum(c['total_sends'] for c in campaigns_list)
    total_opens = sum(c['total_opens'] for c in campaigns_list)
    total_clicks = sum(c['total_clicks'] for c in campaigns_list)
    
    return {
        'count': len(campaigns_list),
        'avg_open_rate': statistics.mean(open_rates) if open_rates else 0,
        'avg_click_rate': statistics.mean(click_rates) if click_rates else 0,
        'total_sends': total_sends,
        'total_opens': total_opens,
        'total_clicks': total_clicks,
        'aggregate_open_rate': total_opens / total_sends if total_sends > 0 else 0,
        'aggregate_click_rate': total_clicks / total_sends if total_sends > 0 else 0,
    }

def main():
    print("=" * 80)
    print("Havenly AI Email Campaign Performance Analysis")
    print("=" * 80)
    print()
    
    campaigns = load_ai_campaigns()
    print(f"Found {len(campaigns)} Havenly AI campaigns\n")
    
    # Show all campaigns
    print("All AI Campaigns:")
    print("-" * 80)
    for campaign in campaigns:
        name = campaign.get('name', '')
        date = campaign.get('_sent_date')
        perf = campaign.get('performance_summary', {})
        if date:
            print(f"{date.strftime('%Y-%m-%d')} | {name}")
            if perf:
                print(f"  Open Rate: {perf.get('open_rate', 0):.2%} | Click Rate: {perf.get('click_rate', 0):.2%} | Sends: {perf.get('total_sends', 0):,}")
        print()
    
    # Analyze by month
    results = analyze_performance(campaigns)
    
    print("\n" + "=" * 80)
    print("Performance by Month")
    print("=" * 80)
    print()
    
    monthly_stats = {}
    for month in sorted(results.keys()):
        stats = calculate_stats(results[month])
        monthly_stats[month] = stats
        if stats:
            print(f"{month}:")
            print(f"  Campaigns: {stats['count']}")
            print(f"  Avg Open Rate: {stats['avg_open_rate']:.2%}")
            print(f"  Avg Click Rate: {stats['avg_click_rate']:.2%}")
            print(f"  Aggregate Open Rate: {stats['aggregate_open_rate']:.2%}")
            print(f"  Aggregate Click Rate: {stats['aggregate_click_rate']:.2%}")
            print(f"  Total Sends: {stats['total_sends']:,}")
            print(f"  Total Opens: {stats['total_opens']:,}")
            print(f"  Total Clicks: {stats['total_clicks']:,}")
            print()
    
    # Compare December 2025 vs other months
    print("\n" + "=" * 80)
    print("December 2025 vs Other Months Comparison")
    print("=" * 80)
    print()
    
    dec_2025 = monthly_stats.get('2025-12')
    other_months = {k: v for k, v in monthly_stats.items() if k != '2025-12' and v}
    
    if dec_2025:
        print("December 2025:")
        print(f"  Avg Open Rate: {dec_2025['avg_open_rate']:.2%}")
        print(f"  Avg Click Rate: {dec_2025['avg_click_rate']:.2%}")
        print(f"  Aggregate Open Rate: {dec_2025['aggregate_open_rate']:.2%}")
        print(f"  Aggregate Click Rate: {dec_2025['aggregate_click_rate']:.2%}")
        print()
        
        if other_months:
            # Calculate averages for other months
            other_open_rates = [v['avg_open_rate'] for v in other_months.values()]
            other_click_rates = [v['avg_click_rate'] for v in other_months.values()]
            other_agg_open = [v['aggregate_open_rate'] for v in other_months.values()]
            other_agg_click = [v['aggregate_click_rate'] for v in other_months.values()]
            
            print("Other Months (Average):")
            print(f"  Avg Open Rate: {statistics.mean(other_open_rates):.2%}")
            print(f"  Avg Click Rate: {statistics.mean(other_click_rates):.2%}")
            print(f"  Aggregate Open Rate: {statistics.mean(other_agg_open):.2%}")
            print(f"  Aggregate Click Rate: {statistics.mean(other_agg_click):.2%}")
            print()
            
            # Calculate differences
            open_diff = dec_2025['avg_open_rate'] - statistics.mean(other_open_rates)
            click_diff = dec_2025['avg_click_rate'] - statistics.mean(other_click_rates)
            agg_open_diff = dec_2025['aggregate_open_rate'] - statistics.mean(other_agg_open)
            agg_click_diff = dec_2025['aggregate_click_rate'] - statistics.mean(other_agg_click)
            
            print("Difference (Dec 2025 vs Other Months):")
            print(f"  Avg Open Rate: {open_diff:+.2%}")
            print(f"  Avg Click Rate: {click_diff:+.2%}")
            print(f"  Aggregate Open Rate: {agg_open_diff:+.2%}")
            print(f"  Aggregate Click Rate: {agg_click_diff:+.2%}")
    
    # Check for February 2026
    print("\n" + "=" * 80)
    print("February 2026 Status")
    print("=" * 80)
    print()
    feb_2026 = monthly_stats.get('2026-02')
    if feb_2026:
        print("February 2026 campaigns found:")
        print(f"  Campaigns: {feb_2026['count']}")
        print(f"  Avg Open Rate: {feb_2026['avg_open_rate']:.2%}")
        print(f"  Avg Click Rate: {feb_2026['avg_click_rate']:.2%}")
    else:
        print("No February 2026 campaigns found in database.")
        print("Data may need to be imported from Braze.")

if __name__ == '__main__':
    main()

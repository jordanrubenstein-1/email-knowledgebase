#!/usr/bin/env python3
"""
Compare Havenly AI email performance: December 2025 vs January 2026
Analyzes weekly cadence impact and engagement trends
"""

import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import statistics

campaigns_dir = Path(__file__).parent.parent.parent / "campaigns"

def load_ai_campaigns():
    """Load Havenly AI email campaigns only (excludes push)."""
    ai_campaigns = []
    
    for yaml_file in campaigns_dir.glob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                campaign = yaml.safe_load(f)
                
            if not campaign:
                continue
                
            # Check if it's Havenly and AI-related (product "Havenly AI")
            # Match _AI or AI_ only — excludes false positives like "Paint", "Email"
            # Email only — exclude push
            brand = campaign.get('brand', '')
            channel = (campaign.get('channel') or '').lower()
            name = campaign.get('name', '').upper()
            is_ai_campaign = ('_AI' in name or 'AI_' in name)
            
            if brand == 'HAV' and channel == 'email' and is_ai_campaign:
                # Get first sent date
                dates = campaign.get('dates', {})
                first_sent = dates.get('first_sent')
                
                if first_sent:
                    try:
                        sent_date = datetime.fromisoformat(first_sent.replace('Z', '+00:00'))
                        campaign['_sent_date'] = sent_date
                        campaign['_sent_month'] = sent_date.strftime('%Y-%m')
                        campaign['_sent_year_month'] = sent_date.strftime('%Y-%m')
                        ai_campaigns.append(campaign)
                    except:
                        pass
        except Exception as e:
            continue
    
    return sorted(ai_campaigns, key=lambda x: x.get('_sent_date', datetime.min))

def analyze_performance(campaigns):
    """Analyze performance metrics by month. Include all AI campaigns in count; rates only from those with performance_summary."""
    results = defaultdict(list)
    
    for campaign in campaigns:
        month = campaign.get('_sent_month', 'unknown')
        perf = campaign.get('performance_summary', {})
        sends = campaign.get('sends', [{}])
        subject = sends[0].get('subject', 'N/A') if sends else 'N/A'
        
        if perf:
            results[month].append({
                'name': campaign.get('name', ''),
                'date': campaign.get('_sent_date'),
                'open_rate': perf.get('open_rate', 0),
                'click_rate': perf.get('click_rate', 0),
                'total_sends': perf.get('total_sends', 0),
                'total_opens': perf.get('total_opens', 0),
                'total_clicks': perf.get('total_clicks', 0),
                'subject': subject,
                'has_metrics': True,
            })
        else:
            # Count push / no-metrics campaigns in total but exclude from rate calcs
            results[month].append({
                'name': campaign.get('name', ''),
                'date': campaign.get('_sent_date'),
                'open_rate': None,
                'click_rate': None,
                'total_sends': 0,
                'total_opens': 0,
                'total_clicks': 0,
                'subject': subject,
                'has_metrics': False,
            })
    
    return results

def calculate_stats(campaigns_list):
    """Calculate aggregate statistics. Count all campaigns; rates/sends only from those with metrics."""
    if not campaigns_list:
        return None
    
    with_metrics = [c for c in campaigns_list if c.get('has_metrics', True) and c.get('open_rate') is not None]
    open_rates = [c['open_rate'] for c in with_metrics if c['open_rate']]
    click_rates = [c['click_rate'] for c in with_metrics if c['click_rate']]
    total_sends = sum(c['total_sends'] for c in campaigns_list)
    total_opens = sum(c['total_opens'] for c in campaigns_list)
    total_clicks = sum(c['total_clicks'] for c in campaigns_list)
    
    return {
        'count': len(campaigns_list),
        'count_with_metrics': len(with_metrics),
        'avg_open_rate': statistics.mean(open_rates) if open_rates else 0,
        'avg_click_rate': statistics.mean(click_rates) if click_rates else 0,
        'total_sends': total_sends,
        'total_opens': total_opens,
        'total_clicks': total_clicks,
        'aggregate_open_rate': total_opens / total_sends if total_sends > 0 else 0,
        'aggregate_click_rate': total_clicks / total_sends if total_sends > 0 else 0,
        'min_open_rate': min(open_rates) if open_rates else 0,
        'max_open_rate': max(open_rates) if open_rates else 0,
        'min_click_rate': min(click_rates) if click_rates else 0,
        'max_click_rate': max(click_rates) if click_rates else 0,
    }

def main():
    print("=" * 80)
    print("Havenly AI Email Performance: December 2025 vs January 2026")
    print("=" * 80)
    print()
    
    campaigns = load_ai_campaigns()
    print(f"Found {len(campaigns)} Havenly AI campaigns total\n")
    
    # Show all campaigns chronologically
    print("All AI Campaigns (Chronological):")
    print("-" * 80)
    for campaign in campaigns:
        name = campaign.get('name', '')
        date = campaign.get('_sent_date')
        perf = campaign.get('performance_summary', {})
        subject = campaign.get('sends', [{}])[0].get('subject', 'N/A') if campaign.get('sends') else 'N/A'
        if date:
            print(f"{date.strftime('%Y-%m-%d')} | {name}")
            print(f"  Subject: {subject}")
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
            print(f"  AI email campaigns: {stats['count']}")
            print(f"  Avg Open Rate: {stats['avg_open_rate']:.2%}")
            print(f"  Avg Click Rate: {stats['avg_click_rate']:.2%}")
            print(f"  Aggregate Open Rate: {stats['aggregate_open_rate']:.2%}")
            print(f"  Aggregate Click Rate: {stats['aggregate_click_rate']:.2%}")
            print(f"  Total Sends: {stats['total_sends']:,}")
            print(f"  Total Opens: {stats['total_opens']:,}")
            print(f"  Total Clicks: {stats['total_clicks']:,}")
            print(f"  Open Rate Range: {stats['min_open_rate']:.2%} - {stats['max_open_rate']:.2%}")
            print(f"  Click Rate Range: {stats['min_click_rate']:.2%} - {stats['max_click_rate']:.2%}")
            print()
    
    # Compare December 2025 vs January 2026
    print("\n" + "=" * 80)
    print("December 2025 vs January 2026 Comparison")
    print("=" * 80)
    print()
    
    dec_2025 = monthly_stats.get('2025-12')
    jan_2026 = monthly_stats.get('2026-01')
    
    if dec_2025:
        print("December 2025:")
        print(f"  AI email campaigns: {dec_2025['count']}")
        print(f"  Avg Open Rate: {dec_2025['avg_open_rate']:.2%}")
        print(f"  Avg Click Rate: {dec_2025['avg_click_rate']:.2%}")
        print(f"  Aggregate Open Rate: {dec_2025['aggregate_open_rate']:.2%}")
        print(f"  Aggregate Click Rate: {dec_2025['aggregate_click_rate']:.2%}")
        print(f"  Total Sends: {dec_2025['total_sends']:,}")
        print()
    
    if jan_2026:
        print("January 2026:")
        print(f"  AI email campaigns: {jan_2026['count']}")
        print(f"  Avg Open Rate: {jan_2026['avg_open_rate']:.2%}")
        print(f"  Avg Click Rate: {jan_2026['avg_click_rate']:.2%}")
        print(f"  Aggregate Open Rate: {jan_2026['aggregate_open_rate']:.2%}")
        print(f"  Aggregate Click Rate: {jan_2026['aggregate_click_rate']:.2%}")
        print(f"  Total Sends: {jan_2026['total_sends']:,}")
        print()
        
        if dec_2025:
            # Calculate differences
            open_diff = jan_2026['avg_open_rate'] - dec_2025['avg_open_rate']
            click_diff = jan_2026['avg_click_rate'] - dec_2025['avg_click_rate']
            agg_open_diff = jan_2026['aggregate_open_rate'] - dec_2025['aggregate_open_rate']
            agg_click_diff = jan_2026['aggregate_click_rate'] - dec_2025['aggregate_click_rate']
            
            print("Change (Jan 2026 vs Dec 2025):")
            print(f"  Avg Open Rate: {open_diff:+.2%}")
            print(f"  Avg Click Rate: {click_diff:+.2%}")
            print(f"  Aggregate Open Rate: {agg_open_diff:+.2%}")
            print(f"  Aggregate Click Rate: {agg_click_diff:+.2%}")
            print()
            
            # Weekly cadence analysis
            if jan_2026['count'] > dec_2025['count']:
                print(f"📈 Weekly Cadence Impact:")
                print(f"  January had {jan_2026['count']} AI email campaigns vs {dec_2025['count']} in December")
                print(f"  This represents a {((jan_2026['count'] / dec_2025['count']) - 1) * 100:.0f}% increase in cadence")
                if open_diff >= 0 and click_diff >= 0:
                    print(f"  ✅ Performance maintained/improved despite increased frequency")
                elif open_diff < -0.05 or click_diff < -0.001:
                    print(f"  ⚠️  Performance declined - possible engagement fatigue")
                else:
                    print(f"  ⚠️  Performance slightly down - monitor closely")
    else:
        print("⚠️  No January 2026 campaigns found.")
        print("   Please run: uv run python scripts/import_braze.py --brand HAV --skip-existing")
        print("   Then re-run this analysis script.")
    
    # Overall trend analysis
    print("\n" + "=" * 80)
    print("Overall Trend Analysis")
    print("=" * 80)
    print()
    
    if len(monthly_stats) >= 2:
        months = sorted(monthly_stats.keys())
        print(f"Tracking performance across {len(months)} months: {', '.join(months)}")
        
        open_trend = [monthly_stats[m]['avg_open_rate'] for m in months if monthly_stats[m]]
        click_trend = [monthly_stats[m]['avg_click_rate'] for m in months if monthly_stats[m]]
        
        if len(open_trend) >= 2:
            open_slope = (open_trend[-1] - open_trend[0]) / len(open_trend)
            click_slope = (click_trend[-1] - click_trend[0]) / len(click_trend)
            
            print(f"  Open Rate Trend: {open_slope:+.2%} per month")
            print(f"  Click Rate Trend: {click_slope:+.2%} per month")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Sale Period Performance Analysis

Dedicated analysis of email campaign performance during sale/promo periods.
Compares performance metrics, timing, and strategies across different sale types.

Outputs: reports/sale-performance-analysis.md
"""

import os
import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.utils.sale_matcher import (
    load_sale_schedules,
    tag_campaigns_with_sales,
    filter_campaigns_by_sale,
    get_sale_context,
)

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


def filter_batch_campaigns(campaigns, channel=None, min_sends=0):
    """Filter to batch campaigns with performance data."""
    batch = []
    for c in campaigns:
        if c.get("braze_type") == "canvas_step":
            continue
        if not c.get("sends"):
            continue
        if channel and c.get("channel") != channel:
            continue
        perf = c.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < min_sends:
            continue
        batch.append(c)
    return batch


def parse_campaign_date(date_str):
    """Parse campaign date to datetime."""
    if not date_str:
        return None
    try:
        date_str = str(date_str).replace("Z", "+00:00")
        if "T" in date_str:
            return datetime.fromisoformat(date_str)
        return datetime.fromisoformat(date_str)
    except:
        return None


def analyze_sale_performance_by_brand(campaigns, sale_schedules):
    """Analyze sale performance broken down by brand."""
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    during_sale = filter_campaigns_by_sale(tagged, during_sale=True, sale_schedules=sale_schedules)
    
    brand_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0,
        "revenue": 0
    })
    
    for c in during_sale:
        brand = c.get("brand", "Unknown")
        perf = c.get("performance_summary", {})
        
        brand_stats[brand]["sends"] += perf.get("total_sends", 0)
        brand_stats[brand]["opens"] += perf.get("total_opens", 0)
        brand_stats[brand]["clicks"] += perf.get("total_clicks", 0)
        brand_stats[brand]["unsubs"] += perf.get("total_unsubscribes", 0)
        brand_stats[brand]["revenue"] += perf.get("total_revenue", 0)
        brand_stats[brand]["count"] += 1
    
    results = []
    for brand, stats in brand_stats.items():
        if stats["sends"] > 0:
            results.append({
                "brand": brand,
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"],
                "revenue": stats["revenue"],
                "revenue_per_send": stats["revenue"] / stats["sends"] if stats["sends"] > 0 else 0,
            })
    
    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_sale_timing(campaigns, sale_schedules):
    """Analyze performance relative to sale start/end dates."""
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    during_sale = filter_campaigns_by_sale(tagged, during_sale=True, sale_schedules=sale_schedules)
    
    # Group by days from sale start
    timing_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "count": 0
    })
    
    for c in during_sale:
        context = c.get("_sale_context", {})
        primary_sale = context.get("primary_sale")
        if not primary_sale:
            continue
        
        sale_start_str = primary_sale.get("start_date")
        if not sale_start_str:
            continue
        
        try:
            sale_start = datetime.strptime(sale_start_str, "%Y-%m-%d")
        except:
            continue
        
        # Get campaign send date
        dates = c.get("dates", {})
        send_date_str = dates.get("last_sent") or dates.get("first_sent")
        send_date = parse_campaign_date(send_date_str)
        
        if not send_date:
            continue
        
        # Calculate days from sale start
        days_from_start = (send_date.date() - sale_start.date()).days
        
        # Bucket: Day 0, Day 1-2, Day 3-5, Day 6-10, Day 11+
        if days_from_start == 0:
            bucket = "Day 0 (Launch)"
        elif days_from_start <= 2:
            bucket = "Days 1-2"
        elif days_from_start <= 5:
            bucket = "Days 3-5"
        elif days_from_start <= 10:
            bucket = "Days 6-10"
        else:
            bucket = "Days 11+"
        
        perf = c.get("performance_summary", {})
        timing_stats[bucket]["sends"] += perf.get("total_sends", 0)
        timing_stats[bucket]["opens"] += perf.get("total_opens", 0)
        timing_stats[bucket]["clicks"] += perf.get("total_clicks", 0)
        timing_stats[bucket]["count"] += 1
    
    results = []
    for bucket in ["Day 0 (Launch)", "Days 1-2", "Days 3-5", "Days 6-10", "Days 11+"]:
        stats = timing_stats.get(bucket, {})
        if stats.get("sends", 0) > 0:
            results.append({
                "timing": bucket,
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
            })
    
    return results


def analyze_sale_type_performance(campaigns, sale_schedules):
    """Analyze performance by sale type."""
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    during_sale = filter_campaigns_by_sale(tagged, during_sale=True, sale_schedules=sale_schedules)
    
    type_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0,
        "sales": set()
    })
    
    for c in during_sale:
        context = c.get("_sale_context", {})
        matching_sales = context.get("matching_sales", [])
        
        for sale in matching_sales:
            sale_type = sale.get("type") or "unspecified"
            type_stats[sale_type]["sales"].add(sale.get("id"))
            
            perf = c.get("performance_summary", {})
            type_stats[sale_type]["sends"] += perf.get("total_sends", 0)
            type_stats[sale_type]["opens"] += perf.get("total_opens", 0)
            type_stats[sale_type]["clicks"] += perf.get("total_clicks", 0)
            type_stats[sale_type]["unsubs"] += perf.get("total_unsubscribes", 0)
            type_stats[sale_type]["count"] += 1
    
    results = []
    for sale_type, stats in type_stats.items():
        if stats["sends"] > 0:
            results.append({
                "type": sale_type,
                "unique_sales": len(stats["sales"]),
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"],
            })
    
    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_sale_overlap(campaigns, sale_schedules):
    """Analyze campaigns that occurred during multiple overlapping sales."""
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    
    overlap_stats = {
        "single_sale": {"sends": 0, "clicks": 0, "count": 0},
        "multiple_sales": {"sends": 0, "clicks": 0, "count": 0},
    }
    
    for c in tagged:
        context = c.get("_sale_context", {})
        if not context.get("during_sale"):
            continue
        
        matching_sales = context.get("matching_sales", [])
        perf = c.get("performance_summary", {})
        
        if len(matching_sales) == 1:
            key = "single_sale"
        else:
            key = "multiple_sales"
        
        overlap_stats[key]["sends"] += perf.get("total_sends", 0)
        overlap_stats[key]["clicks"] += perf.get("total_clicks", 0)
        overlap_stats[key]["count"] += 1
    
    return overlap_stats


def format_pct(value, decimals=2):
    """Format a decimal as percentage."""
    return f"{value * 100:.{decimals}f}%"


def format_number(value):
    """Format large numbers with commas."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(int(value))


def generate_report(campaigns, sale_schedules):
    """Generate the sale performance analysis report."""
    lines = []
    
    lines.append("# Sale Period Performance Analysis\n\n")
    lines.append(f"> Analysis of {len(sale_schedules)} sale periods across email campaigns\n\n")
    lines.append("---\n\n")
    
    # Tag campaigns
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    during_sale = filter_campaigns_by_sale(tagged, during_sale=True, sale_schedules=sale_schedules)
    not_during_sale = filter_campaigns_by_sale(tagged, during_sale=False, sale_schedules=sale_schedules)
    
    lines.append(f"**Dataset:** {len(during_sale):,} campaigns during sale periods, {len(not_during_sale):,} campaigns outside sale periods\n\n")
    
    # Overall comparison
    lines.append("## Overall Performance: Sale vs Non-Sale\n\n")
    
    def calc_stats(campaign_list):
        total_sends = sum(c.get("performance_summary", {}).get("total_sends", 0) for c in campaign_list)
        total_opens = sum(c.get("performance_summary", {}).get("total_opens", 0) for c in campaign_list)
        total_clicks = sum(c.get("performance_summary", {}).get("total_clicks", 0) for c in campaign_list)
        total_unsubs = sum(c.get("performance_summary", {}).get("total_unsubscribes", 0) for c in campaign_list)
        total_revenue = sum(c.get("performance_summary", {}).get("total_revenue", 0) for c in campaign_list)
        
        return {
            "campaigns": len(campaign_list),
            "sends": total_sends,
            "opens": total_opens,
            "clicks": total_clicks,
            "unsubs": total_unsubs,
            "revenue": total_revenue,
            "open_rate": total_opens / total_sends if total_sends > 0 else 0,
            "click_rate": total_clicks / total_sends if total_sends > 0 else 0,
            "unsub_rate": total_unsubs / total_sends if total_sends > 0 else 0,
            "revenue_per_send": total_revenue / total_sends if total_sends > 0 else 0,
        }
    
    sale_stats = calc_stats(during_sale)
    non_sale_stats = calc_stats(not_during_sale)
    
    lines.append("| Metric | During Sale | Not During Sale | Difference |\n")
    lines.append("|--------|-------------|-----------------|-----------|\n")
    
    if sale_stats["sends"] > 0 and non_sale_stats["sends"] > 0:
        click_lift = (sale_stats["click_rate"] / non_sale_stats["click_rate"] - 1) * 100 if non_sale_stats["click_rate"] > 0 else 0
        lines.append(f"| Click Rate | {format_pct(sale_stats['click_rate'])} | {format_pct(non_sale_stats['click_rate'])} | {click_lift:+.1f}% |\n")
        
        open_lift = (sale_stats["open_rate"] / non_sale_stats["open_rate"] - 1) * 100 if non_sale_stats["open_rate"] > 0 else 0
        lines.append(f"| Open Rate | {format_pct(sale_stats['open_rate'])} | {format_pct(non_sale_stats['open_rate'])} | {open_lift:+.1f}% |\n")
        
        unsub_lift = (sale_stats["unsub_rate"] / non_sale_stats["unsub_rate"] - 1) * 100 if non_sale_stats["unsub_rate"] > 0 else 0
        lines.append(f"| Unsub Rate | {format_pct(sale_stats['unsub_rate'])} | {format_pct(non_sale_stats['unsub_rate'])} | {unsub_lift:+.1f}% |\n")
        
        if sale_stats["revenue"] > 0 or non_sale_stats["revenue"] > 0:
            rev_lift = (sale_stats["revenue_per_send"] / non_sale_stats["revenue_per_send"] - 1) * 100 if non_sale_stats["revenue_per_send"] > 0 else 0
            lines.append(f"| Revenue/Send | ${sale_stats['revenue_per_send']:.2f} | ${non_sale_stats['revenue_per_send']:.2f} | {rev_lift:+.1f}% |\n")
    
    lines.append("\n")
    
    # Performance by brand
    lines.append("## Sale Performance by Brand\n\n")
    brand_stats = analyze_sale_performance_by_brand(campaigns, sale_schedules)
    
    lines.append("| Brand | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate | Revenue/Send |\n")
    lines.append("|-------|----------|-------|-----------|------------|------------|--------------|\n")
    
    for b in brand_stats:
        lines.append(f"| {b['brand']} | {b['campaigns']:,} | {format_number(b['sends'])} | {format_pct(b['open_rate'])} | {format_pct(b['click_rate'])} | {format_pct(b['unsub_rate'])} | ${b['revenue_per_send']:.2f} |\n")
    
    lines.append("\n")
    
    # Performance by sale type
    lines.append("## Performance by Sale Type\n\n")
    type_stats = analyze_sale_type_performance(campaigns, sale_schedules)
    
    if type_stats:
        lines.append("| Sale Type | Unique Sales | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
        lines.append("|-----------|-------------|-----------|-------|-----------|------------|------------|\n")
        
        for t in type_stats:
            lines.append(f"| {t['type']} | {t['unique_sales']} | {t['campaigns']:,} | {format_number(t['sends'])} | {format_pct(t['open_rate'])} | {format_pct(t['click_rate'])} | {format_pct(t['unsub_rate'])} |\n")
        
        lines.append("\n")
    
    # Timing analysis
    lines.append("## Performance by Timing Relative to Sale Start\n\n")
    lines.append("*How campaign performance varies based on days from sale launch*\n\n")
    
    timing_stats = analyze_sale_timing(campaigns, sale_schedules)
    
    if timing_stats:
        lines.append("| Timing | Campaigns | Sends | Open Rate | Click Rate |\n")
        lines.append("|--------|-----------|-------|-----------|------------|\n")
        
        for t in timing_stats:
            lines.append(f"| {t['timing']} | {t['campaigns']:,} | {format_number(t['sends'])} | {format_pct(t['open_rate'])} | {format_pct(t['click_rate'])} |\n")
        
        lines.append("\n")
    
    # Sale overlap analysis
    lines.append("## Sale Overlap Analysis\n\n")
    lines.append("*Performance when campaigns occur during single vs multiple concurrent sales*\n\n")
    
    overlap_stats = analyze_sale_overlap(campaigns, sale_schedules)
    
    lines.append("| Scenario | Campaigns | Sends | Click Rate |\n")
    lines.append("|----------|-----------|-------|------------|\n")
    
    single = overlap_stats["single_sale"]
    multiple = overlap_stats["multiple_sales"]
    
    if single["sends"] > 0:
        single_rate = single["clicks"] / single["sends"]
        lines.append(f"| Single Sale | {single['count']:,} | {format_number(single['sends'])} | {format_pct(single_rate)} |\n")
    
    if multiple["sends"] > 0:
        multiple_rate = multiple["clicks"] / multiple["sends"]
        lines.append(f"| Multiple Sales | {multiple['count']:,} | {format_number(multiple['sends'])} | {format_pct(multiple_rate)} |\n")
    
    lines.append("\n")
    
    # Key insights
    lines.append("## Key Insights\n\n")
    
    insights = []
    
    if sale_stats["click_rate"] > 0 and non_sale_stats["click_rate"] > 0:
        lift = (sale_stats["click_rate"] / non_sale_stats["click_rate"] - 1) * 100
        if abs(lift) > 5:
            if lift > 0:
                insights.append(f"**Sale periods drive {lift:.0f}% higher click rates** — {format_pct(sale_stats['click_rate'])} vs {format_pct(non_sale_stats['click_rate'])} outside sales.")
            else:
                insights.append(f"**Non-sale periods outperform by {abs(lift):.0f}%** — Possible sale fatigue or better targeting outside promotional periods.")
    
    if timing_stats:
        best_timing = max(timing_stats, key=lambda x: x["click_rate"])
        insights.append(f"**Best timing: {best_timing['timing']}** — {format_pct(best_timing['click_rate'])} click rate when sending {best_timing['timing'].lower()}.")
    
    if type_stats:
        best_type = max(type_stats, key=lambda x: x["click_rate"])
        insights.append(f"**Best sale type: {best_type['type']}** — {format_pct(best_type['click_rate'])} click rate across {best_type['unique_sales']} sales.")
    
    if brand_stats:
        best_brand = max(brand_stats, key=lambda x: x["click_rate"])
        insights.append(f"**{best_brand['brand']} leads during sales** — {format_pct(best_brand['click_rate'])} click rate with {best_brand['campaigns']:,} campaigns.")
    
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}\n\n")
    
    lines.append("---\n\n")
    lines.append(f"*Analysis generated {datetime.now().strftime('%B %d, %Y')}*\n")
    
    return "".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sale period performance analysis")
    parser.add_argument("--min-sends", type=int, default=0,
                        help="Minimum total_sends to include a campaign (default: 0; use 1000 to filter to Braze-only data)")
    args = parser.parse_args()

    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaign files")

    batch_campaigns = filter_batch_campaigns(campaigns, channel="email", min_sends=args.min_sends)
    threshold_note = f"{args.min_sends}+ sends" if args.min_sends > 0 else "all sends (incl. 0)"
    print(f"Found {len(batch_campaigns)} batch email campaigns ({threshold_note})")
    
    # Load sale schedules
    sale_schedules = load_sale_schedules()
    if not sale_schedules:
        print("Warning: No sale schedules found. Create data/sale_schedules.yaml first.")
        print("Run: uv run python scripts/import_sale_schedules.py --source csv --file <path>")
        return
    
    print(f"Loaded {len(sale_schedules)} sale periods from schedule")
    
    print("\nGenerating sale performance analysis...")
    report = generate_report(batch_campaigns, sale_schedules)
    
    # Write report
    report_path = Path(__file__).parent.parent / "reports" / "sale-performance-analysis.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, "w") as f:
        f.write(report)
    
    print(f"\nReport written to {report_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()

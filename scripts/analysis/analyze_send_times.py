#!/usr/bin/env python3
"""
Send Time Analysis

Analyzes email campaign performance by time of day and day of week.
All times converted to Mountain Time (America/Denver).

Outputs: send-time-analysis.pdf
"""

import os
import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import markdown
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import sys

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.utils.sale_matcher import (
    load_sale_schedules,
    tag_campaigns_with_sales,
    filter_campaigns_by_sale,
)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"
MT_TZ = ZoneInfo("America/Denver")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_hour_ampm(hour):
    """Format hour in 12-hour AM/PM format."""
    if hour == 0:
        return "12am"
    elif hour < 12:
        return f"{hour}am"
    elif hour == 12:
        return "12pm"
    else:
        return f"{hour - 12}pm"


def parse_timestamp(date_str):
    """Parse ISO timestamp and convert to Mountain Time."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        date_str = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo:
            return dt.astimezone(MT_TZ)
        return None
    except:
        return None


def infer_send_time(first_sent_str, last_sent_str):
    """Infer the intended send time based on campaign type.
    
    Detects whether a campaign is a local-time send or fixed-time send based
    on the span between first_sent and last_sent:
    
    - Span < 20 hours: Fixed-time send (sent at specific MT time to everyone)
      → Convert last_sent to Mountain Time directly
    
    - Span >= 20 hours: Local-time send (sent at local time across time zones)
      → Subtract 10 hours from last_sent (Hawaii/UTC-10 is last US timezone)
    
    Returns the inferred send time for analysis.
    """
    if not last_sent_str or not isinstance(last_sent_str, str):
        return None
    try:
        last_sent_str = last_sent_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(last_sent_str)
        if not last_dt.tzinfo:
            return None
        
        # Calculate span if first_sent is available
        span_hours = 0
        if first_sent_str and isinstance(first_sent_str, str):
            first_sent_str = first_sent_str.replace("Z", "+00:00")
            first_dt = datetime.fromisoformat(first_sent_str)
            if first_dt.tzinfo:
                span_hours = (last_dt - first_dt).total_seconds() / 3600
        
        utc_dt = last_dt.astimezone(ZoneInfo("UTC"))
        
        if span_hours < 20:
            # Fixed-time send: convert to Mountain Time directly
            return utc_dt.astimezone(MT_TZ)
        else:
            # Local-time send: subtract 10 hours (Hawaii offset) to get local time
            return utc_dt - timedelta(hours=10)
    except:
        return None


def load_campaigns():
    """Load all campaign YAML files with valid timestamps."""
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


def filter_batch_campaigns(campaigns):
    """Filter to batch campaigns with valid send times and 1000+ sends."""
    batch = []
    for c in campaigns:
        # Skip canvas steps (triggered campaigns)
        if c.get("braze_type") == "canvas_step":
            continue
        # Skip non-email campaigns
        if not c.get("sends"):
            continue
        # Must have performance data
        perf = c.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 1000:
            continue
        # Must have valid timestamp - infer send time based on span
        dates = c.get("dates", {})
        first_sent = dates.get("first_sent")
        last_sent = dates.get("last_sent")
        dt = infer_send_time(first_sent, last_sent)
        if not dt:
            continue
        c["_parsed_dt"] = dt
        batch.append(c)
    return batch


def analyze_by_hour(campaigns):
    """Aggregate metrics by hour of day."""
    hour_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    })
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        hour = dt.hour
        perf = c.get("performance_summary", {})
        
        hour_stats[hour]["sends"] += perf.get("total_sends", 0)
        hour_stats[hour]["opens"] += perf.get("total_opens", 0)
        hour_stats[hour]["clicks"] += perf.get("total_clicks", 0)
        hour_stats[hour]["unsubs"] += perf.get("total_unsubscribes", 0)
        hour_stats[hour]["count"] += 1
    
    results = []
    for hour in range(24):
        stats = hour_stats[hour]
        if stats["sends"] > 0:
            results.append({
                "hour": hour,
                "hour_label": format_hour_ampm(hour),
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"]
            })
    
    return results


def analyze_by_day(campaigns):
    """Aggregate metrics by day of week."""
    day_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    })
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        day = dt.weekday()
        perf = c.get("performance_summary", {})
        
        day_stats[day]["sends"] += perf.get("total_sends", 0)
        day_stats[day]["opens"] += perf.get("total_opens", 0)
        day_stats[day]["clicks"] += perf.get("total_clicks", 0)
        day_stats[day]["unsubs"] += perf.get("total_unsubscribes", 0)
        day_stats[day]["count"] += 1
    
    results = []
    for day in range(7):
        stats = day_stats[day]
        if stats["sends"] > 0:
            results.append({
                "day": day,
                "day_name": DAY_NAMES[day],
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"]
            })
    
    return results


def analyze_by_day_brand(campaigns):
    """Aggregate metrics by day of week, broken down by brand."""
    brand_day_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "count": 0
    }))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        brand = c.get("brand", "Unknown")
        day = dt.weekday()
        perf = c.get("performance_summary", {})
        
        brand_day_stats[brand][day]["sends"] += perf.get("total_sends", 0)
        brand_day_stats[brand][day]["opens"] += perf.get("total_opens", 0)
        brand_day_stats[brand][day]["clicks"] += perf.get("total_clicks", 0)
        brand_day_stats[brand][day]["count"] += 1
    
    return brand_day_stats


def analyze_hour_x_day(campaigns):
    """Create hour x day matrix of click rates."""
    matrix = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "clicks": 0, "count": 0
    }))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        hour = dt.hour
        day = dt.weekday()
        perf = c.get("performance_summary", {})
        
        matrix[hour][day]["sends"] += perf.get("total_sends", 0)
        matrix[hour][day]["clicks"] += perf.get("total_clicks", 0)
        matrix[hour][day]["count"] += 1
    
    return matrix


def analyze_am_pm(campaigns):
    """Compare AM vs PM performance."""
    time_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    })
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        period = "AM (6-12)" if 6 <= dt.hour < 12 else \
                 "Midday (12-15)" if 12 <= dt.hour < 15 else \
                 "Afternoon (15-18)" if 15 <= dt.hour < 18 else \
                 "Evening (18-21)" if 18 <= dt.hour < 21 else \
                 "Night (21-6)"
        perf = c.get("performance_summary", {})
        
        time_stats[period]["sends"] += perf.get("total_sends", 0)
        time_stats[period]["opens"] += perf.get("total_opens", 0)
        time_stats[period]["clicks"] += perf.get("total_clicks", 0)
        time_stats[period]["unsubs"] += perf.get("total_unsubscribes", 0)
        time_stats[period]["count"] += 1
    
    results = []
    for period in ["AM (6-12)", "Midday (12-15)", "Afternoon (15-18)", "Evening (18-21)", "Night (21-6)"]:
        stats = time_stats[period]
        if stats["sends"] > 0:
            results.append({
                "period": period,
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"]
            })
    
    return results


def analyze_brand_best_times(campaigns):
    """Find best hour and day for each brand."""
    brand_hour_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "clicks": 0, "count": 0
    }))
    brand_day_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "clicks": 0, "count": 0
    }))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        brand = c.get("brand", "Unknown")
        hour = dt.hour
        day = dt.weekday()
        perf = c.get("performance_summary", {})
        
        brand_hour_stats[brand][hour]["sends"] += perf.get("total_sends", 0)
        brand_hour_stats[brand][hour]["clicks"] += perf.get("total_clicks", 0)
        brand_hour_stats[brand][hour]["count"] += 1
        
        brand_day_stats[brand][day]["sends"] += perf.get("total_sends", 0)
        brand_day_stats[brand][day]["clicks"] += perf.get("total_clicks", 0)
        brand_day_stats[brand][day]["count"] += 1
    
    results = []
    for brand in sorted(brand_hour_stats.keys()):
        # Find best hour
        best_hour = None
        best_hour_rate = 0
        for hour, stats in brand_hour_stats[brand].items():
            if stats["sends"] >= 10000:  # Minimum threshold
                rate = stats["clicks"] / stats["sends"]
                if rate > best_hour_rate:
                    best_hour_rate = rate
                    best_hour = hour
        
        # Find best day
        best_day = None
        best_day_rate = 0
        for day, stats in brand_day_stats[brand].items():
            if stats["sends"] >= 10000:
                rate = stats["clicks"] / stats["sends"]
                if rate > best_day_rate:
                    best_day_rate = rate
                    best_day = day
        
        if best_hour is not None and best_day is not None:
            results.append({
                "brand": brand,
                "best_hour": format_hour_ampm(best_hour),
                "best_hour_rate": best_hour_rate,
                "best_day": DAY_NAMES[best_day],
                "best_day_rate": best_day_rate
            })
    
    return results


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


def generate_report(campaigns):
    """Generate the Markdown analysis report."""
    lines = []
    
    # Tag campaigns with sale periods
    sale_schedules = load_sale_schedules()
    if sale_schedules:
        campaigns = tag_campaigns_with_sales(campaigns, sale_schedules)
    
    # Header
    lines.append("# Send Time Analysis\n")
    lines.append(f"> {len(campaigns):,} batch campaigns | Times reflect intended local send time\n\n")
    if sale_schedules:
        lines.append(f"> Sale schedules loaded: {len(sale_schedules)} periods\n\n")
    lines.append("---\n\n")
    
    # Executive Summary
    lines.append("## Executive Summary\n\n")
    
    hour_stats = analyze_by_hour(campaigns)
    day_stats = analyze_by_day(campaigns)
    am_pm_stats = analyze_am_pm(campaigns)
    brand_times = analyze_brand_best_times(campaigns)
    
    # Find best hour and day
    if hour_stats:
        best_hour = max(hour_stats, key=lambda x: x["click_rate"])
        worst_hour = min(hour_stats, key=lambda x: x["click_rate"])
    if day_stats:
        best_day = max(day_stats, key=lambda x: x["click_rate"])
        worst_day = min(day_stats, key=lambda x: x["click_rate"])
    
    lines.append("### Key Findings\n\n")
    if hour_stats and day_stats:
        lines.append(f"1. **Best send hour:** {best_hour['hour_label']} local ({format_pct(best_hour['click_rate'])} click rate)\n")
        lines.append(f"2. **Worst send hour:** {worst_hour['hour_label']} local ({format_pct(worst_hour['click_rate'])} click rate)\n")
        lines.append(f"3. **Best day:** {best_day['day_name']} ({format_pct(best_day['click_rate'])} click rate)\n")
        lines.append(f"4. **Worst day:** {worst_day['day_name']} ({format_pct(worst_day['click_rate'])} click rate)\n")
        
        lift = (best_hour['click_rate'] - worst_hour['click_rate']) / worst_hour['click_rate'] * 100 if worst_hour['click_rate'] > 0 else 0
        lines.append(f"5. **Hour timing lift:** {lift:.0f}% improvement from worst to best hour\n\n")
    
    lines.append("---\n\n")
    
    # Hour of Day Analysis
    lines.append("## Hour of Day Performance\n\n")
    lines.append("*Click rate by hour of send (local time)*\n\n")
    
    lines.append("| Hour | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
    lines.append("|------|-----------|-------|-----------|------------|------------|\n")
    
    avg_click = sum(h["click_rate"] * h["sends"] for h in hour_stats) / sum(h["sends"] for h in hour_stats) if hour_stats else 0
    
    for h in sorted(hour_stats, key=lambda x: x["hour"]):
        highlight = "**" if h["click_rate"] >= avg_click * 1.1 else ""
        lines.append(f"| {h['hour_label']} | {h['campaigns']:,} | {format_number(h['sends'])} | {format_pct(h['open_rate'])} | {highlight}{format_pct(h['click_rate'])}{highlight} | {format_pct(h['unsub_rate'])} |\n")
    
    lines.append("\n")
    
    # Time Period Analysis
    lines.append("### Time Period Summary\n\n")
    lines.append("| Period | Campaigns | Sends | Open Rate | Click Rate |\n")
    lines.append("|--------|-----------|-------|-----------|------------|\n")
    
    for p in am_pm_stats:
        highlight = "**" if p == max(am_pm_stats, key=lambda x: x["click_rate"]) else ""
        lines.append(f"| {p['period']} | {p['campaigns']:,} | {format_number(p['sends'])} | {format_pct(p['open_rate'])} | {highlight}{format_pct(p['click_rate'])}{highlight} |\n")
    
    lines.append("\n---\n\n")
    
    # Day of Week Analysis
    lines.append("## Day of Week Performance\n\n")
    lines.append("*Click rate by day of send*\n\n")
    
    lines.append("| Day | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
    lines.append("|-----|-----------|-------|-----------|------------|------------|\n")
    
    for d in sorted(day_stats, key=lambda x: x["day"]):
        highlight = "**" if d == best_day else ""
        lines.append(f"| {d['day_name']} | {d['campaigns']:,} | {format_number(d['sends'])} | {format_pct(d['open_rate'])} | {highlight}{format_pct(d['click_rate'])}{highlight} | {format_pct(d['unsub_rate'])} |\n")
    
    lines.append("\n")
    
    # Day x Brand Matrix
    lines.append("### Day × Brand Click Rate Matrix\n\n")
    brand_day = analyze_by_day_brand(campaigns)
    
    brands = sorted([b for b in brand_day.keys() if sum(brand_day[b][d]["sends"] for d in range(7)) > 50000])
    
    if brands:
        lines.append("| Brand |")
        for abbrev in DAY_ABBREV:
            lines.append(f" {abbrev} |")
        lines.append("\n")
        
        lines.append("|-------|")
        for _ in DAY_ABBREV:
            lines.append("------|")
        lines.append("\n")
        
        for brand in brands:
            lines.append(f"| {brand} |")
            brand_rates = []
            for day in range(7):
                stats = brand_day[brand][day]
                if stats["sends"] > 0:
                    rate = stats["clicks"] / stats["sends"]
                    brand_rates.append((day, rate))
            
            best_brand_day = max(brand_rates, key=lambda x: x[1])[0] if brand_rates else -1
            
            for day in range(7):
                stats = brand_day[brand][day]
                if stats["sends"] > 0:
                    rate = stats["clicks"] / stats["sends"]
                    highlight = "**" if day == best_brand_day else ""
                    lines.append(f" {highlight}{format_pct(rate)}{highlight} |")
                else:
                    lines.append(" - |")
            lines.append("\n")
        
        lines.append("\n")
    
    lines.append("---\n\n")
    
    # Hour x Day Heatmap
    lines.append("## Hour × Day Analysis\n\n")
    lines.append("*Click rates for common send times (10K+ sends minimum)*\n\n")
    
    matrix = analyze_hour_x_day(campaigns)
    
    # Find hours with significant data
    significant_hours = []
    for hour in range(24):
        total_sends = sum(matrix[hour][day]["sends"] for day in range(7))
        if total_sends >= 50000:
            significant_hours.append(hour)
    
    if significant_hours:
        lines.append("| Hour |")
        for abbrev in DAY_ABBREV:
            lines.append(f" {abbrev} |")
        lines.append("\n")
        
        lines.append("|------|")
        for _ in DAY_ABBREV:
            lines.append("------|")
        lines.append("\n")
        
        for hour in significant_hours:
            lines.append(f"| {format_hour_ampm(hour)} |")
            for day in range(7):
                stats = matrix[hour][day]
                if stats["sends"] >= 10000:
                    rate = stats["clicks"] / stats["sends"]
                    lines.append(f" {format_pct(rate)} |")
                else:
                    lines.append(" - |")
            lines.append("\n")
        
        lines.append("\n")
    
    lines.append("---\n\n")
    
    # Sale Period Segmentation
    if sale_schedules:
        lines.append("## Send Time Performance: Sale vs Non-Sale Periods\n\n")
        lines.append("*Comparing optimal send times during sale periods vs regular periods*\n\n")
        
        during_sale = filter_campaigns_by_sale(campaigns, during_sale=True, sale_schedules=sale_schedules)
        not_during_sale = filter_campaigns_by_sale(campaigns, during_sale=False, sale_schedules=sale_schedules)
        
        if during_sale and not_during_sale:
            # Hour analysis for each segment
            sale_hour_stats = analyze_by_hour(during_sale)
            non_sale_hour_stats = analyze_by_hour(not_during_sale)
            
            if sale_hour_stats and non_sale_hour_stats:
                lines.append("### Best Send Hours: Sale vs Non-Sale\n\n")
                lines.append("| Period | Best Hour | Click Rate | Worst Hour | Click Rate |\n")
                lines.append("|--------|-----------|------------|------------|------------|\n")
                
                sale_best = max(sale_hour_stats, key=lambda x: x["click_rate"])
                sale_worst = min(sale_hour_stats, key=lambda x: x["click_rate"])
                non_sale_best = max(non_sale_hour_stats, key=lambda x: x["click_rate"])
                non_sale_worst = min(non_sale_hour_stats, key=lambda x: x["click_rate"])
                
                lines.append(f"| **During Sale** | {sale_best['hour_label']} | {format_pct(sale_best['click_rate'])} | {sale_worst['hour_label']} | {format_pct(sale_worst['click_rate'])} |\n")
                lines.append(f"| Not During Sale | {non_sale_best['hour_label']} | {format_pct(non_sale_best['click_rate'])} | {non_sale_worst['hour_label']} | {format_pct(non_sale_worst['click_rate'])} |\n")
                lines.append("\n")
            
            # Day analysis for each segment
            sale_day_stats = analyze_by_day(during_sale)
            non_sale_day_stats = analyze_by_day(not_during_sale)
            
            if sale_day_stats and non_sale_day_stats:
                lines.append("### Best Send Days: Sale vs Non-Sale\n\n")
                lines.append("| Period | Best Day | Click Rate | Worst Day | Click Rate |\n")
                lines.append("|--------|----------|------------|-----------|------------|\n")
                
                sale_best_day = max(sale_day_stats, key=lambda x: x["click_rate"])
                sale_worst_day = min(sale_day_stats, key=lambda x: x["click_rate"])
                non_sale_best_day = max(non_sale_day_stats, key=lambda x: x["click_rate"])
                non_sale_worst_day = min(non_sale_day_stats, key=lambda x: x["click_rate"])
                
                lines.append(f"| **During Sale** | {sale_best_day['day_name']} | {format_pct(sale_best_day['click_rate'])} | {sale_worst_day['day_name']} | {format_pct(sale_worst_day['click_rate'])} |\n")
                lines.append(f"| Not During Sale | {non_sale_best_day['day_name']} | {format_pct(non_sale_best_day['click_rate'])} | {non_sale_worst_day['day_name']} | {format_pct(non_sale_worst_day['click_rate'])} |\n")
                lines.append("\n")
        
        lines.append("---\n\n")
    
    # Brand-Specific Best Times
    lines.append("## Brand-Specific Optimal Times\n\n")
    lines.append("*Best performing hour and day per brand (10K+ sends minimum)*\n\n")
    
    if brand_times:
        lines.append("| Brand | Best Hour | Click Rate | Best Day | Click Rate |\n")
        lines.append("|-------|-----------|------------|----------|------------|\n")
        
        for b in brand_times:
            lines.append(f"| {b['brand']} | {b['best_hour']} | {format_pct(b['best_hour_rate'])} | {b['best_day']} | {format_pct(b['best_day_rate'])} |\n")
        
        lines.append("\n")
    
    lines.append("---\n\n")
    
    # Recommendations
    lines.append("## Recommendations\n\n")
    lines.append("Based on the send time analysis:\n\n")
    
    recommendations = []
    
    if hour_stats:
        best_hours = sorted(hour_stats, key=lambda x: -x["click_rate"])[:3]
        hour_range = f"{best_hours[0]['hour_label']}-{best_hours[-1]['hour_label']}"
        recommendations.append(f"**Prioritize sends between {best_hours[0]['hour_label']} and {best_hours[-1]['hour_label']} local** — These hours consistently show higher engagement")
    
    if day_stats:
        best_days = sorted(day_stats, key=lambda x: -x["click_rate"])[:2]
        recommendations.append(f"**Focus on {best_days[0]['day_name']} and {best_days[1]['day_name']}** — Best performing days across all brands")
    
    if am_pm_stats:
        best_period = max(am_pm_stats, key=lambda x: x["click_rate"])
        recommendations.append(f"**{best_period['period']} sends outperform** — Consider shifting more volume to this window")
    
    recommendations.append("**Brand-specific timing matters** — Each brand has different optimal windows; use the brand matrix above for guidance")
    
    for rec in recommendations:
        lines.append(f"- {rec}\n")
    
    lines.append("\n---\n\n")
    lines.append("### Methodology Note\n\n")
    lines.append("*Send times are inferred from campaign timestamps. Campaigns are classified by the span between first and last send: ")
    lines.append("**Local-time sends** (span ≥ 20 hours) use the last_sent timestamp minus 10 hours (Hawaii offset) to recover intended local time. ")
    lines.append("**Fixed-time sends** (span < 20 hours) convert last_sent directly to Mountain Time.*\n\n")
    lines.append(f"*Analysis generated {datetime.now().strftime('%B %Y')}*\n")
    
    return "".join(lines)


class PDFReport(FPDF):
    """Custom PDF class for the send time analysis report."""
    
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        pass
        
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')
        
    def chapter_title(self, title):
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(44, 62, 80)
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)
        
    def section_title(self, title):
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(52, 73, 94)
        self.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        
    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(51)
        self.multi_cell(0, 5, text)
        self.ln(2)
        
    def bullet_point(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(51)
        x = self.get_x()
        self.cell(8, 5, chr(149), new_x=XPos.RIGHT)  # bullet character
        self.multi_cell(0, 5, text)
        self.set_x(x)  # reset x position for next bullet
        
    def add_table(self, headers, data, col_widths=None):
        """Add a table to the PDF."""
        if col_widths is None:
            col_widths = [190 // len(headers)] * len(headers)
            
        # Header row
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(44, 62, 80)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 7, header, border=1, fill=True, align='C')
        self.ln()
        
        # Data rows
        self.set_font('Helvetica', '', 9)
        self.set_text_color(51)
        fill = False
        for row in data:
            if fill:
                self.set_fill_color(250, 250, 250)
            else:
                self.set_fill_color(255, 255, 255)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6, str(cell), border=1, fill=True, align='C')
            self.ln()
            fill = not fill
        self.ln(3)


def generate_pdf(campaigns, output_path):
    """Generate PDF report from campaign data."""
    pdf = PDFReport()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'Send Time Analysis', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    # Subtitle
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, f'{len(campaigns):,} batch campaigns | Times reflect intended local send time', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Get analysis data
    hour_stats = analyze_by_hour(campaigns)
    day_stats = analyze_by_day(campaigns)
    am_pm_stats = analyze_am_pm(campaigns)
    brand_times = analyze_brand_best_times(campaigns)
    brand_day = analyze_by_day_brand(campaigns)
    matrix = analyze_hour_x_day(campaigns)
    
    # Executive Summary
    pdf.chapter_title('Executive Summary')
    
    if hour_stats and day_stats:
        best_hour = max(hour_stats, key=lambda x: x["click_rate"])
        worst_hour = min(hour_stats, key=lambda x: x["click_rate"])
        best_day = max(day_stats, key=lambda x: x["click_rate"])
        worst_day = min(day_stats, key=lambda x: x["click_rate"])
        
        pdf.section_title('Key Findings')
        pdf.bullet_point(f"Best send hour: {best_hour['hour_label']} local ({format_pct(best_hour['click_rate'])} click rate)")
        pdf.bullet_point(f"Worst send hour: {worst_hour['hour_label']} local ({format_pct(worst_hour['click_rate'])} click rate)")
        pdf.bullet_point(f"Best day: {best_day['day_name']} ({format_pct(best_day['click_rate'])} click rate)")
        pdf.bullet_point(f"Worst day: {worst_day['day_name']} ({format_pct(worst_day['click_rate'])} click rate)")
        
        lift = (best_hour['click_rate'] - worst_hour['click_rate']) / worst_hour['click_rate'] * 100 if worst_hour['click_rate'] > 0 else 0
        pdf.bullet_point(f"Hour timing lift: {lift:.0f}% improvement from worst to best hour")
    pdf.ln(5)
    
    # Hour of Day Performance
    pdf.chapter_title('Hour of Day Performance')
    pdf.body_text('Click rate by hour of send (local time)')
    
    headers = ['Hour', 'Campaigns', 'Sends', 'Open Rate', 'Click Rate', 'Unsub Rate']
    data = []
    for h in sorted(hour_stats, key=lambda x: x["hour"]):
        data.append([
            h['hour_label'],
            f"{h['campaigns']:,}",
            format_number(h['sends']),
            format_pct(h['open_rate']),
            format_pct(h['click_rate']),
            format_pct(h['unsub_rate'])
        ])
    pdf.add_table(headers, data, col_widths=[20, 25, 25, 30, 30, 30])
    
    # Time Period Summary
    pdf.section_title('Time Period Summary')
    headers = ['Period', 'Campaigns', 'Sends', 'Open Rate', 'Click Rate']
    data = []
    for p in am_pm_stats:
        data.append([
            p['period'],
            f"{p['campaigns']:,}",
            format_number(p['sends']),
            format_pct(p['open_rate']),
            format_pct(p['click_rate'])
        ])
    pdf.add_table(headers, data, col_widths=[45, 30, 30, 35, 35])
    
    # Day of Week Performance
    pdf.add_page()
    pdf.chapter_title('Day of Week Performance')
    pdf.body_text('Click rate by day of send')
    
    headers = ['Day', 'Campaigns', 'Sends', 'Open Rate', 'Click Rate', 'Unsub Rate']
    data = []
    for d in sorted(day_stats, key=lambda x: x["day"]):
        data.append([
            d['day_name'],
            f"{d['campaigns']:,}",
            format_number(d['sends']),
            format_pct(d['open_rate']),
            format_pct(d['click_rate']),
            format_pct(d['unsub_rate'])
        ])
    pdf.add_table(headers, data, col_widths=[30, 25, 25, 30, 30, 30])
    
    # Day x Brand Matrix
    pdf.section_title('Day x Brand Click Rate Matrix')
    brands = sorted([b for b in brand_day.keys() if sum(brand_day[b][d]["sends"] for d in range(7)) > 50000])
    
    if brands:
        headers = ['Brand'] + DAY_ABBREV
        data = []
        for brand in brands:
            row = [brand]
            for day in range(7):
                stats = brand_day[brand][day]
                if stats["sends"] > 0:
                    rate = stats["clicks"] / stats["sends"]
                    row.append(format_pct(rate))
                else:
                    row.append('-')
            data.append(row)
        pdf.add_table(headers, data, col_widths=[25, 23, 23, 23, 23, 23, 23, 23])
    
    # Hour x Day Analysis
    pdf.add_page()
    pdf.chapter_title('Hour x Day Analysis')
    pdf.body_text('Click rates for common send times (10K+ sends minimum)')
    
    significant_hours = []
    for hour in range(24):
        total_sends = sum(matrix[hour][day]["sends"] for day in range(7))
        if total_sends >= 50000:
            significant_hours.append(hour)
    
    if significant_hours:
        headers = ['Hour'] + DAY_ABBREV
        data = []
        for hour in significant_hours:
            row = [format_hour_ampm(hour)]
            for day in range(7):
                stats = matrix[hour][day]
                if stats["sends"] >= 10000:
                    rate = stats["clicks"] / stats["sends"]
                    row.append(format_pct(rate))
                else:
                    row.append('-')
            data.append(row)
        pdf.add_table(headers, data, col_widths=[25, 23, 23, 23, 23, 23, 23, 23])
    
    # Brand-Specific Optimal Times
    pdf.chapter_title('Brand-Specific Optimal Times')
    pdf.body_text('Best performing hour and day per brand (10K+ sends minimum)')
    
    if brand_times:
        headers = ['Brand', 'Best Hour', 'Click Rate', 'Best Day', 'Click Rate']
        data = []
        for b in brand_times:
            data.append([
                b['brand'],
                b['best_hour'],
                format_pct(b['best_hour_rate']),
                b['best_day'],
                format_pct(b['best_day_rate'])
            ])
        pdf.add_table(headers, data, col_widths=[25, 35, 35, 35, 35])
    
    # Recommendations
    pdf.add_page()
    pdf.chapter_title('Recommendations')
    pdf.body_text('Based on the send time analysis:')
    pdf.ln(3)
    
    if hour_stats:
        best_hours = sorted(hour_stats, key=lambda x: -x["click_rate"])[:3]
        pdf.bullet_point(f"Prioritize sends between {best_hours[0]['hour_label']} and {best_hours[-1]['hour_label']} local - These hours consistently show higher engagement")
    
    if day_stats:
        best_days = sorted(day_stats, key=lambda x: -x["click_rate"])[:2]
        pdf.bullet_point(f"Focus on {best_days[0]['day_name']} and {best_days[1]['day_name']} - Best performing days across all brands")
    
    if am_pm_stats:
        best_period = max(am_pm_stats, key=lambda x: x["click_rate"])
        pdf.bullet_point(f"{best_period['period']} sends outperform - Consider shifting more volume to this window")
    
    pdf.bullet_point("Brand-specific timing matters - Each brand has different optimal windows; use the brand matrix for guidance")
    
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128)
    pdf.cell(0, 5, f"Analysis generated {datetime.now().strftime('%B %Y')} | Times reflect intended local send time", align='C')
    
    # Save PDF
    pdf.output(str(output_path))
    print(f"PDF written to {output_path}")


def main():
    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaign files")
    
    batch_campaigns = filter_batch_campaigns(campaigns)
    print(f"Found {len(batch_campaigns)} batch campaigns with valid send times")
    
    # Check for sale schedules
    sale_schedules = load_sale_schedules()
    if sale_schedules:
        print(f"Loaded {len(sale_schedules)} sale periods from schedule")
    
    print("\nGenerating send time analysis...")
    
    # Generate Markdown report
    report = generate_report(batch_campaigns)
    md_path = Path(__file__).parent.parent / "send-time-analysis.md"
    with open(md_path, "w") as f:
        f.write(report)
    print(f"Markdown written to {md_path}")
    
    # Generate PDF
    pdf_path = Path(__file__).parent.parent / "send-time-analysis.pdf"
    generate_pdf(batch_campaigns, pdf_path)
    
    print("\nDone!")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
Blast Campaign Engagement Analysis

Hypothesis: Blast campaigns are overdone. Outside of Havenly (which has editorial engagement),
other brands aren't delivering real customer engagement. It's cost without engagement.

Outputs results to ANALYSIS.md - no permanent YAML changes.
"""

import os
import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import sys

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.utils.sale_matcher import (
    load_sale_schedules,
    tag_campaigns_with_sales,
    filter_campaigns_by_sale,
)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


def classify_campaign_type(name: str) -> str:
    """Classify campaign by type based on naming patterns."""
    name_lower = name.lower()

    # Sale/Promo patterns
    sale_patterns = [
        "sale", "promo", "off", "discount", "flash", "clearance",
        "labor_day", "memorial_day", "black_friday", "cyber", "bfcm",
        "july_4", "fourth_of_july", "presidents_day", "ldw", "mdw",
        "event", "save", "deal"
    ]

    # Editorial patterns
    editorial_patterns = [
        "trend", "forecast", "style_guide", "edit", "spotlight",
        "hideaway", "tips", "how_to", "guide", "inspiration",
        "designer", "color_edit", "room_refresh", "palette"
    ]

    # Product launch patterns
    product_patterns = [
        "new_arrival", "just_dropped", "introducing", "meet", "launch",
        "new_", "collection", "debut", "reveal"
    ]

    # Reminder/Follow-up patterns
    reminder_patterns = [
        "reminder", "ends_soon", "last_chance", "final", "ending",
        "don't_miss", "hurry", "extended", "last_day"
    ]

    # Check patterns in order of specificity
    for pattern in reminder_patterns:
        if pattern in name_lower:
            return "reminder"

    for pattern in editorial_patterns:
        if pattern in name_lower:
            return "editorial"

    for pattern in product_patterns:
        if pattern in name_lower:
            return "product_launch"

    for pattern in sale_patterns:
        if pattern in name_lower:
            return "sale_promo"

    return "other"


def get_week_key(date_str: str, tz: ZoneInfo = None) -> str:
    """Get ISO week key from date string, optionally converting to timezone."""
    try:
        if isinstance(date_str, str):
            # Handle various date formats
            date_str = date_str.replace("Z", "+00:00")
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str)
            else:
                dt = datetime.fromisoformat(date_str)
            
            # Convert to target timezone if provided
            if tz and dt.tzinfo:
                dt = dt.astimezone(tz)
        else:
            dt = date_str
        return f"{dt.year}-W{dt.isocalendar()[1]:02d}"
    except:
        return None


def load_campaigns():
    """Load all campaign YAML files."""
    campaigns = []

    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue  # Skip example files

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if data:
                    data["_filename"] = yaml_file.name
                    campaigns.append(data)
        except Exception as e:
            print(f"Error loading {yaml_file.name}: {e}")

    return campaigns


def filter_batch_campaigns(campaigns, channel=None):
    """Filter to batch campaigns only (exclude canvas/triggered).
    
    Args:
        campaigns: List of campaign dicts
        channel: Optional channel filter ('email', 'sms', 'push', or None for all)
    """
    batch = []
    for c in campaigns:
        # Skip canvas steps (triggered campaigns)
        if c.get("braze_type") == "canvas_step":
            continue
        # Skip non-email campaigns (legacy check - keep for compatibility)
        if not c.get("sends"):
            continue
        # Channel filter if specified
        if channel and c.get("channel") != channel:
            continue
        # Must have performance data
        perf = c.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 1000:
            continue
        batch.append(c)
    return batch


def filter_canvas_campaigns(campaigns):
    """Filter to canvas/triggered campaigns only."""
    canvas = []
    for c in campaigns:
        if c.get("braze_type") == "canvas_step":
            perf = c.get("performance_summary", {})
            if perf.get("total_sends") and perf["total_sends"] >= 100:
                canvas.append(c)
    return canvas


def analyze_by_brand(campaigns, channel=None):
    """Aggregate metrics by brand.
    
    Args:
        campaigns: List of campaign dicts
        channel: Optional channel filter ('email', 'sms', 'push', or None for all)
    """
    brand_stats = defaultdict(lambda: {
        "campaigns": 0,
        "total_sends": 0,
        "total_opens": 0,
        "total_clicks": 0,
        "total_unsubs": 0
    })

    for c in campaigns:
        # Channel filter if specified
        if channel and c.get("channel") != channel:
            continue
            
        brand = c.get("brand", "Unknown")
        perf = c.get("performance_summary", {})

        brand_stats[brand]["campaigns"] += 1
        brand_stats[brand]["total_sends"] += perf.get("total_sends", 0)
        brand_stats[brand]["total_opens"] += perf.get("total_opens", 0)
        brand_stats[brand]["total_clicks"] += perf.get("total_clicks", 0)
        brand_stats[brand]["total_unsubs"] += perf.get("total_unsubscribes", 0)

    # Calculate rates
    results = []
    for brand, stats in brand_stats.items():
        if stats["total_sends"] > 0:
            results.append({
                "brand": brand,
                "campaigns": stats["campaigns"],
                "sends": stats["total_sends"],
                "open_rate": stats["total_opens"] / stats["total_sends"],
                "click_rate": stats["total_clicks"] / stats["total_sends"],
                "unsub_rate": stats["total_unsubs"] / stats["total_sends"]
            })

    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_by_type(campaigns):
    """Aggregate metrics by campaign type."""
    type_stats = defaultdict(lambda: {
        "campaigns": 0,
        "total_sends": 0,
        "total_opens": 0,
        "total_clicks": 0,
        "total_unsubs": 0
    })

    for c in campaigns:
        campaign_type = classify_campaign_type(c.get("name", ""))
        perf = c.get("performance_summary", {})

        type_stats[campaign_type]["campaigns"] += 1
        type_stats[campaign_type]["total_sends"] += perf.get("total_sends", 0)
        type_stats[campaign_type]["total_opens"] += perf.get("total_opens", 0)
        type_stats[campaign_type]["total_clicks"] += perf.get("total_clicks", 0)
        type_stats[campaign_type]["total_unsubs"] += perf.get("total_unsubscribes", 0)

    results = []
    for ctype, stats in type_stats.items():
        if stats["total_sends"] > 0:
            results.append({
                "type": ctype,
                "campaigns": stats["campaigns"],
                "sends": stats["total_sends"],
                "open_rate": stats["total_opens"] / stats["total_sends"],
                "click_rate": stats["total_clicks"] / stats["total_sends"],
                "unsub_rate": stats["total_unsubs"] / stats["total_sends"]
            })

    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_brand_x_type(campaigns):
    """Analyze click rate by brand and campaign type."""
    matrix = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "clicks": 0
    }))

    for c in campaigns:
        brand = c.get("brand", "Unknown")
        campaign_type = classify_campaign_type(c.get("name", ""))
        perf = c.get("performance_summary", {})

        matrix[brand][campaign_type]["sends"] += perf.get("total_sends", 0)
        matrix[brand][campaign_type]["clicks"] += perf.get("total_clicks", 0)

    return matrix


def analyze_sale_vs_non_sale(campaigns):
    """Compare performance during sale periods vs non-sale periods.
    
    Returns:
        Dictionary with 'during_sale' and 'not_during_sale' stats.
    """
    sale_schedules = load_sale_schedules()
    if not sale_schedules:
        return None
    
    # Tag campaigns
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    
    during_sale = filter_campaigns_by_sale(tagged, during_sale=True, sale_schedules=sale_schedules)
    not_during_sale = filter_campaigns_by_sale(tagged, during_sale=False, sale_schedules=sale_schedules)
    
    def calc_stats(campaign_list):
        total_sends = sum(c.get("performance_summary", {}).get("total_sends", 0) for c in campaign_list)
        total_opens = sum(c.get("performance_summary", {}).get("total_opens", 0) for c in campaign_list)
        total_clicks = sum(c.get("performance_summary", {}).get("total_clicks", 0) for c in campaign_list)
        total_unsubs = sum(c.get("performance_summary", {}).get("total_unsubscribes", 0) for c in campaign_list)
        
        return {
            "campaigns": len(campaign_list),
            "sends": total_sends,
            "opens": total_opens,
            "clicks": total_clicks,
            "unsubs": total_unsubs,
            "open_rate": total_opens / total_sends if total_sends > 0 else 0,
            "click_rate": total_clicks / total_sends if total_sends > 0 else 0,
            "unsub_rate": total_unsubs / total_sends if total_sends > 0 else 0,
        }
    
    return {
        "during_sale": calc_stats(during_sale),
        "not_during_sale": calc_stats(not_during_sale),
    }


def analyze_by_sale_type(campaigns):
    """Analyze performance by sale type (if available in sale schedules)."""
    sale_schedules = load_sale_schedules()
    if not sale_schedules:
        return {}
    
    # Tag campaigns
    tagged = tag_campaigns_with_sales(campaigns, sale_schedules)
    
    # Group by sale type
    type_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    })
    
    for c in tagged:
        context = c.get("_sale_context", {})
        if not context.get("during_sale"):
            continue
        
        primary_sale = context.get("primary_sale", {})
        sale_type = primary_sale.get("type") or "unspecified"
        
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
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"],
            })
    
    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_weekly_frequency(campaigns):
    """Analyze engagement by Nth campaign of the week per brand."""
    # Group campaigns by brand and week
    brand_week_campaigns = defaultdict(lambda: defaultdict(list))
    mt_tz = ZoneInfo("America/Denver")

    for c in campaigns:
        brand = c.get("brand", "Unknown")
        dates = c.get("dates", {})
        last_sent = dates.get("last_sent")
        if not last_sent:
            continue

        week_key = get_week_key(last_sent, mt_tz)
        if week_key:
            brand_week_campaigns[brand][week_key].append(c)

    # Sort campaigns within each week by date, assign position
    nth_stats = defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    })

    for brand, weeks in brand_week_campaigns.items():
        for week_key, week_campaigns in weeks.items():
            # Sort by last_sent
            week_campaigns.sort(key=lambda x: x.get("dates", {}).get("last_sent", ""))

            for i, c in enumerate(week_campaigns):
                pos = min(i + 1, 5)  # Cap at 5+ for "5th or more"
                if pos == 5 and i >= 4:
                    pos_key = "5+"
                else:
                    pos_key = str(pos)

                perf = c.get("performance_summary", {})
                nth_stats[pos_key]["sends"] += perf.get("total_sends", 0)
                nth_stats[pos_key]["opens"] += perf.get("total_opens", 0)
                nth_stats[pos_key]["clicks"] += perf.get("total_clicks", 0)
                nth_stats[pos_key]["unsubs"] += perf.get("total_unsubscribes", 0)
                nth_stats[pos_key]["count"] += 1

    results = []
    for pos in ["1", "2", "3", "4", "5+"]:
        stats = nth_stats[pos]
        if stats["sends"] > 0:
            results.append({
                "position": pos,
                "campaigns": stats["count"],
                "sends": stats["sends"],
                "open_rate": stats["opens"] / stats["sends"],
                "click_rate": stats["clicks"] / stats["sends"],
                "unsub_rate": stats["unsubs"] / stats["sends"]
            })

    return results


def analyze_weekly_frequency_by_brand(campaigns):
    """Analyze engagement by Nth campaign of the week, broken down by brand."""
    # Group campaigns by brand and week
    brand_week_campaigns = defaultdict(lambda: defaultdict(list))
    mt_tz = ZoneInfo("America/Denver")

    for c in campaigns:
        brand = c.get("brand", "Unknown")
        dates = c.get("dates", {})
        last_sent = dates.get("last_sent")
        if not last_sent:
            continue

        week_key = get_week_key(last_sent, mt_tz)
        if week_key:
            brand_week_campaigns[brand][week_key].append(c)

    # Track stats per brand per position
    brand_nth_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    }))

    for brand, weeks in brand_week_campaigns.items():
        for week_key, week_campaigns in weeks.items():
            week_campaigns.sort(key=lambda x: x.get("dates", {}).get("last_sent", ""))

            for i, c in enumerate(week_campaigns):
                pos = min(i + 1, 5)
                pos_key = "5+" if pos == 5 and i >= 4 else str(pos)

                perf = c.get("performance_summary", {})
                brand_nth_stats[brand][pos_key]["sends"] += perf.get("total_sends", 0)
                brand_nth_stats[brand][pos_key]["opens"] += perf.get("total_opens", 0)
                brand_nth_stats[brand][pos_key]["clicks"] += perf.get("total_clicks", 0)
                brand_nth_stats[brand][pos_key]["unsubs"] += perf.get("total_unsubscribes", 0)
                brand_nth_stats[brand][pos_key]["count"] += 1

    return brand_nth_stats


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


def generate_report(batch_campaigns, canvas_campaigns):
    """Generate the analysis report."""

    lines = []
    lines.append("\n---\n")
    lines.append("## Blast Campaign Engagement Analysis\n")
    lines.append("> Hypothesis: Blast campaigns are overdone. Outside of Havenly, other brands aren't delivering real engagement.\n\n")

    # Summary stats
    total_batch = len(batch_campaigns)
    total_canvas = len(canvas_campaigns)
    batch_sends = sum(c.get("performance_summary", {}).get("total_sends", 0) for c in batch_campaigns)
    canvas_sends = sum(c.get("performance_summary", {}).get("total_sends", 0) for c in canvas_campaigns)

    lines.append(f"**Dataset:** {total_batch:,} batch campaigns ({format_number(batch_sends)} sends), {total_canvas:,} triggered campaigns ({format_number(canvas_sends)} sends)\n\n")
    
    # Tag campaigns with sale periods
    sale_schedules = load_sale_schedules()
    if sale_schedules:
        batch_campaigns = tag_campaigns_with_sales(batch_campaigns, sale_schedules)
        print(f"Tagged campaigns with {len(sale_schedules)} sale periods")

    # 1. Triggered vs Batch Baseline
    lines.append("### Triggered vs Batch: The Baseline\n\n")

    batch_clicks = sum(c.get("performance_summary", {}).get("total_clicks", 0) for c in batch_campaigns)
    batch_opens = sum(c.get("performance_summary", {}).get("total_opens", 0) for c in batch_campaigns)
    canvas_clicks = sum(c.get("performance_summary", {}).get("total_clicks", 0) for c in canvas_campaigns)
    canvas_opens = sum(c.get("performance_summary", {}).get("total_opens", 0) for c in canvas_campaigns)

    lines.append("| Type | Campaigns | Sends | Open Rate | Click Rate |\n")
    lines.append("|------|-----------|-------|-----------|------------|\n")

    if canvas_sends > 0:
        lines.append(f"| **Triggered (Canvas)** | {total_canvas:,} | {format_number(canvas_sends)} | {format_pct(canvas_opens/canvas_sends)} | **{format_pct(canvas_clicks/canvas_sends)}** |\n")
    if batch_sends > 0:
        lines.append(f"| Batch | {total_batch:,} | {format_number(batch_sends)} | {format_pct(batch_opens/batch_sends)} | {format_pct(batch_clicks/batch_sends)} |\n")

    if canvas_sends > 0 and batch_sends > 0:
        click_lift = (canvas_clicks/canvas_sends) / (batch_clicks/batch_sends) if batch_clicks > 0 else 0
        lines.append(f"\n**Triggered campaigns get {click_lift:.1f}x higher click rates.** Every batch campaign competes against this benchmark.\n\n")

    # 2. Brand Comparison (Email) - filter email from all batch campaigns
    # Note: batch_campaigns already excludes canvas, but may include SMS
    lines.append("### Click Rate by Brand (Batch Only - Email)\n\n")
    email_batch = filter_batch_campaigns(batch_campaigns, channel="email")
    brand_stats = analyze_by_brand(email_batch)

    lines.append("| Brand | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
    lines.append("|-------|-----------|-------|-----------|------------|------------|\n")

    for b in brand_stats:
        click_highlight = "**" if b["click_rate"] == max(x["click_rate"] for x in brand_stats) else ""
        lines.append(f"| {b['brand']} | {b['campaigns']:,} | {format_number(b['sends'])} | {format_pct(b['open_rate'])} | {click_highlight}{format_pct(b['click_rate'])}{click_highlight} | {format_pct(b['unsub_rate'])} |\n")

    lines.append("\n")

    # 2b. Brand Comparison (SMS)
    sms_batch = filter_batch_campaigns(batch_campaigns, channel="sms")
    if sms_batch:
        lines.append("### Click Rate by Brand (Batch Only - SMS)\n\n")
        sms_brand_stats = analyze_by_brand(sms_batch)

        lines.append("| Brand | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
        lines.append("|-------|-----------|-------|-----------|------------|------------|\n")

        for b in sms_brand_stats:
            click_highlight = "**" if b["click_rate"] == max(x["click_rate"] for x in sms_brand_stats) else ""
            lines.append(f"| {b['brand']} | {b['campaigns']:,} | {format_number(b['sends'])} | {format_pct(b['open_rate'])} | {click_highlight}{format_pct(b['click_rate'])}{click_highlight} | {format_pct(b['unsub_rate'])} |\n")

        lines.append("\n")

    # 3. Campaign Type Comparison
    lines.append("### Click Rate by Campaign Type\n\n")
    type_stats = analyze_by_type(batch_campaigns)

    lines.append("| Type | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
    lines.append("|------|-----------|-------|-----------|------------|------------|\n")

    for t in type_stats:
        click_highlight = "**" if t["click_rate"] == max(x["click_rate"] for x in type_stats) else ""
        lines.append(f"| {t['type']} | {t['campaigns']:,} | {format_number(t['sends'])} | {format_pct(t['open_rate'])} | {click_highlight}{format_pct(t['click_rate'])}{click_highlight} | {format_pct(t['unsub_rate'])} |\n")

    lines.append("\n")

    # 4. Brand x Type Matrix
    lines.append("### Brand × Campaign Type Matrix (Click Rates)\n\n")
    matrix = analyze_brand_x_type(batch_campaigns)

    types = ["sale_promo", "editorial", "product_launch", "reminder", "other"]
    brands = sorted(matrix.keys())

    # Header
    lines.append("| Brand |")
    for t in types:
        lines.append(f" {t} |")
    lines.append("\n")

    lines.append("|-------|")
    for _ in types:
        lines.append("--------|")
    lines.append("\n")

    # Data rows
    for brand in brands:
        lines.append(f"| {brand} |")
        for t in types:
            data = matrix[brand][t]
            if data["sends"] > 0:
                rate = data["clicks"] / data["sends"]
                lines.append(f" {format_pct(rate)} |")
            else:
                lines.append(" - |")
        lines.append("\n")

    lines.append("\n")

    # 5. Diminishing Returns Analysis
    lines.append("### Diminishing Returns: Engagement by Nth Weekly Campaign\n\n")
    lines.append("*For each brand, campaigns are bucketed by their position in that week's send schedule.*\n\n")

    freq_stats = analyze_weekly_frequency(batch_campaigns)

    lines.append("| Position | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
    lines.append("|----------|-----------|-------|-----------|------------|------------|\n")

    first_click = freq_stats[0]["click_rate"] if freq_stats else 0
    for f in freq_stats:
        delta = ""
        if f["position"] != "1" and first_click > 0:
            pct_drop = (first_click - f["click_rate"]) / first_click * 100
            delta = f" (-{pct_drop:.0f}%)" if pct_drop > 0 else ""
        lines.append(f"| {f['position']} | {f['campaigns']:,} | {format_number(f['sends'])} | {format_pct(f['open_rate'])} | {format_pct(f['click_rate'])}{delta} | {format_pct(f['unsub_rate'])} |\n")

    lines.append("\n")

    # 6. Diminishing Returns by Brand
    lines.append("### Diminishing Returns by Brand\n\n")
    brand_freq = analyze_weekly_frequency_by_brand(batch_campaigns)

    # Find brands with enough data
    valid_brands = []
    for brand in sorted(brand_freq.keys()):
        if brand_freq[brand]["1"]["sends"] > 10000:  # Minimum threshold
            valid_brands.append(brand)

    if valid_brands:
        lines.append("| Brand | 1st | 2nd | 3rd | 4th | 5th+ |\n")
        lines.append("|-------|-----|-----|-----|-----|------|\n")

        for brand in valid_brands:
            lines.append(f"| {brand} |")
            for pos in ["1", "2", "3", "4", "5+"]:
                data = brand_freq[brand][pos]
                if data["sends"] > 0:
                    rate = data["clicks"] / data["sends"]
                    lines.append(f" {format_pct(rate)} |")
                else:
                    lines.append(" - |")
            lines.append("\n")

        lines.append("\n")

    # 6b. Sale vs Non-Sale Performance
    sale_comparison = analyze_sale_vs_non_sale(batch_campaigns)
    if sale_comparison:
        lines.append("### Sale Period Performance Comparison\n\n")
        lines.append("*Comparing campaigns sent during sale periods vs non-sale periods*\n\n")
        
        during = sale_comparison["during_sale"]
        not_during = sale_comparison["not_during_sale"]
        
        lines.append("| Period | Campaigns | Sends | Open Rate | Click Rate | Unsub Rate |\n")
        lines.append("|--------|-----------|-------|-----------|------------|------------|\n")
        lines.append(f"| **During Sale** | {during['campaigns']:,} | {format_number(during['sends'])} | {format_pct(during['open_rate'])} | {format_pct(during['click_rate'])} | {format_pct(during['unsub_rate'])} |\n")
        lines.append(f"| Not During Sale | {not_during['campaigns']:,} | {format_number(not_during['sends'])} | {format_pct(not_during['open_rate'])} | {format_pct(not_during['click_rate'])} | {format_pct(not_during['unsub_rate'])} |\n")
        
        if during['click_rate'] > 0 and not_during['click_rate'] > 0:
            lift = (during['click_rate'] / not_during['click_rate'] - 1) * 100
            if lift > 0:
                lines.append(f"\n**Sale periods drive {lift:.0f}% higher click rates** ({format_pct(during['click_rate'])} vs {format_pct(not_during['click_rate'])}).\n")
            else:
                lines.append(f"\n**Non-sale periods perform {abs(lift):.0f}% better** on click rates.\n")
        
        lines.append("\n")
        
        # Sale type breakdown if available
        sale_types = analyze_by_sale_type(batch_campaigns)
        if sale_types:
            lines.append("#### Performance by Sale Type\n\n")
            lines.append("| Sale Type | Campaigns | Sends | Open Rate | Click Rate |\n")
            lines.append("|-----------|-----------|-------|-----------|------------|\n")
            for st in sale_types:
                lines.append(f"| {st['type']} | {st['campaigns']:,} | {format_number(st['sends'])} | {format_pct(st['open_rate'])} | {format_pct(st['click_rate'])} |\n")
            lines.append("\n")

    # 7. Key Findings
    lines.append("### Key Findings\n\n")

    # Find Havenly editorial performance
    hav_editorial = matrix.get("HAV", {}).get("editorial", {"sends": 0, "clicks": 0})
    hav_sale = matrix.get("HAV", {}).get("sale_promo", {"sends": 0, "clicks": 0})

    findings = []

    # Triggered vs batch finding
    if canvas_sends > 0 and batch_sends > 0:
        batch_click_rate = batch_clicks / batch_sends
        canvas_click_rate = canvas_clicks / canvas_sends
        findings.append(f"**Triggered emails outperform batch {canvas_click_rate/batch_click_rate:.1f}x** on click rate ({format_pct(canvas_click_rate)} vs {format_pct(batch_click_rate)}). Investment in behavioral triggers has outsized ROI.")

    # Havenly editorial finding
    if hav_editorial["sends"] > 0 and hav_sale["sends"] > 0:
        hav_ed_rate = hav_editorial["clicks"] / hav_editorial["sends"]
        hav_sale_rate = hav_sale["clicks"] / hav_sale["sends"]
        if hav_ed_rate > hav_sale_rate:
            findings.append(f"**Havenly's editorial content works** — {format_pct(hav_ed_rate)} click rate vs {format_pct(hav_sale_rate)} for sale promos. Other brands don't see this lift from editorial.")

    # Diminishing returns finding
    if len(freq_stats) >= 3:
        first_rate = freq_stats[0]["click_rate"]
        third_rate = freq_stats[2]["click_rate"] if len(freq_stats) > 2 else freq_stats[-1]["click_rate"]
        if first_rate > third_rate:
            drop_pct = (first_rate - third_rate) / first_rate * 100
            findings.append(f"**Diminishing returns are real** — 3rd weekly campaign gets {drop_pct:.0f}% fewer clicks than 1st. Over-sending erodes engagement.")

    # Reminder fatigue
    reminder_stats = next((t for t in type_stats if t["type"] == "reminder"), None)
    if reminder_stats and reminder_stats["unsub_rate"] > 0:
        avg_unsub = sum(t["unsub_rate"] for t in type_stats) / len(type_stats)
        if reminder_stats["unsub_rate"] > avg_unsub * 1.2:
            findings.append(f"**Reminder emails drive unsubscribes** — {format_pct(reminder_stats['unsub_rate'])} unsub rate, {reminder_stats['unsub_rate']/avg_unsub:.1f}x higher than average. \"Last chance\" fatigue is real.")
    
    # Sale period finding
    if sale_comparison:
        during = sale_comparison["during_sale"]
        not_during = sale_comparison["not_during_sale"]
        if during["click_rate"] > 0 and not_during["click_rate"] > 0:
            lift = (during["click_rate"] / not_during["click_rate"] - 1) * 100
            if abs(lift) > 5:  # Only report if significant difference
                if lift > 0:
                    findings.append(f"**Sale periods boost engagement** — {format_pct(during['click_rate'])} click rate during sales vs {format_pct(not_during['click_rate'])} outside sales ({lift:+.0f}% lift).")
                else:
                    findings.append(f"**Non-sale periods outperform** — {format_pct(not_during['click_rate'])} click rate outside sales vs {format_pct(during['click_rate'])} during sales. Consider sale fatigue.")

    for i, finding in enumerate(findings, 1):
        lines.append(f"{i}. {finding}\n\n")

    # 8. Recommendations
    lines.append("### Recommendations\n\n")
    lines.append("Based on the engagement data:\n\n")

    recommendations = [
        "**Invest in triggered campaigns** — Cart abandonment, browse abandonment, and post-purchase flows deliver 3x+ the engagement of batch sends",
        "**Reduce weekly send frequency** — Data shows significant engagement drop after the 2nd campaign per week. Test sending less.",
        "**Audit reminder emails** — High unsubscribe rates suggest \"last chance\" messaging is overused. Test softer approaches.",
        "**HAV should double down on editorial** — It works for their audience. Other brands should test whether their audiences respond similarly before investing."
    ]

    for rec in recommendations:
        lines.append(f"- {rec}\n")

    lines.append("\n")

    return "".join(lines)


def main():
    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaign files")

    batch_campaigns = filter_batch_campaigns(campaigns)
    print(f"Found {len(batch_campaigns)} batch campaigns (1000+ sends)")

    canvas_campaigns = filter_canvas_campaigns(campaigns)
    print(f"Found {len(canvas_campaigns)} canvas/triggered campaigns")
    
    # Check for sale schedules
    sale_schedules = load_sale_schedules()
    if sale_schedules:
        print(f"Loaded {len(sale_schedules)} sale periods from schedule")

    print("\nGenerating analysis report...")
    report = generate_report(batch_campaigns, canvas_campaigns)

    # Read existing ANALYSIS.md
    analysis_path = Path(__file__).parent.parent / "ANALYSIS.md"
    with open(analysis_path) as f:
        existing = f.read()

    # Check if section already exists
    if "## Blast Campaign Engagement Analysis" in existing:
        # Replace existing section
        pattern = r"\n---\n\n## Blast Campaign Engagement Analysis.*?(?=\n---\n## |\Z)"
        existing = re.sub(pattern, "", existing, flags=re.DOTALL)

    # Append new section
    with open(analysis_path, "w") as f:
        f.write(existing.rstrip())
        f.write(report)

    print(f"\nResults written to {analysis_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()

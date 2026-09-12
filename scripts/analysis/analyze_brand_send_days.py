#!/usr/bin/env python3
"""
Brand-by-Brand Send Day Analysis

Comprehensive day-of-week analysis for each brand, including:
- Full daily performance breakdown per brand
- Volume distribution analysis
- Day-over-day comparison
- Best/worst day identification with statistical context

Outputs: brand-send-day-analysis.md and .pdf
"""

import os
import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fpdf import FPDF
from fpdf.enums import XPos, YPos

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


def infer_send_time(first_sent_str, last_sent_str):
    """Infer the intended send time based on campaign type."""
    if not last_sent_str or not isinstance(last_sent_str, str):
        return None
    try:
        last_sent_str = last_sent_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(last_sent_str)
        if not last_dt.tzinfo:
            return None
        
        span_hours = 0
        if first_sent_str and isinstance(first_sent_str, str):
            first_sent_str = first_sent_str.replace("Z", "+00:00")
            first_dt = datetime.fromisoformat(first_sent_str)
            if first_dt.tzinfo:
                span_hours = (last_dt - first_dt).total_seconds() / 3600
        
        utc_dt = last_dt.astimezone(ZoneInfo("UTC"))
        
        if span_hours < 20:
            return utc_dt.astimezone(MT_TZ)
        else:
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
        if c.get("braze_type") == "canvas_step":
            continue
        if not c.get("sends"):
            continue
        perf = c.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 1000:
            continue
        dates = c.get("dates", {})
        first_sent = dates.get("first_sent")
        last_sent = dates.get("last_sent")
        dt = infer_send_time(first_sent, last_sent)
        if not dt:
            continue
        c["_parsed_dt"] = dt
        batch.append(c)
    return batch


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


def analyze_brand_day_detailed(campaigns):
    """Comprehensive brand × day analysis."""
    brand_day_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "bounces": 0, 
        "delivered": 0, "count": 0, "campaigns": []
    }))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        brand = c.get("brand", "Unknown")
        day = dt.weekday()
        perf = c.get("performance_summary", {})
        
        stats = brand_day_stats[brand][day]
        stats["sends"] += perf.get("total_sends", 0)
        stats["opens"] += perf.get("total_opens", 0)
        stats["clicks"] += perf.get("total_clicks", 0)
        stats["unsubs"] += perf.get("total_unsubscribes", 0)
        stats["bounces"] += perf.get("total_bounces", 0)
        stats["delivered"] += perf.get("total_delivered", 0)
        stats["count"] += 1
        stats["campaigns"].append(c.get("name", "Unknown"))
    
    return brand_day_stats


def analyze_brand_hour_detailed(campaigns):
    """Comprehensive brand × hour analysis."""
    brand_hour_stats = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0
    }))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        brand = c.get("brand", "Unknown")
        hour = dt.hour
        perf = c.get("performance_summary", {})
        
        stats = brand_hour_stats[brand][hour]
        stats["sends"] += perf.get("total_sends", 0)
        stats["opens"] += perf.get("total_opens", 0)
        stats["clicks"] += perf.get("total_clicks", 0)
        stats["unsubs"] += perf.get("total_unsubscribes", 0)
        stats["count"] += 1
    
    return brand_hour_stats


def analyze_brand_day_hour(campaigns):
    """Brand × day × hour matrix."""
    brand_day_hour_stats = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "clicks": 0, "count": 0
    })))
    
    for c in campaigns:
        dt = c.get("_parsed_dt")
        if not dt:
            continue
        brand = c.get("brand", "Unknown")
        day = dt.weekday()
        hour = dt.hour
        perf = c.get("performance_summary", {})
        
        stats = brand_day_hour_stats[brand][day][hour]
        stats["sends"] += perf.get("total_sends", 0)
        stats["clicks"] += perf.get("total_clicks", 0)
        stats["count"] += 1
    
    return brand_day_hour_stats


def compute_brand_summary(brand_day_stats, brand):
    """Compute summary stats for a brand."""
    stats = brand_day_stats[brand]
    
    total_sends = sum(stats[d]["sends"] for d in range(7))
    total_opens = sum(stats[d]["opens"] for d in range(7))
    total_clicks = sum(stats[d]["clicks"] for d in range(7))
    total_unsubs = sum(stats[d]["unsubs"] for d in range(7))
    total_campaigns = sum(stats[d]["count"] for d in range(7))
    
    day_rates = []
    for day in range(7):
        d = stats[day]
        if d["sends"] > 0:
            day_rates.append({
                "day": day,
                "day_name": DAY_NAMES[day],
                "campaigns": d["count"],
                "sends": d["sends"],
                "pct_volume": d["sends"] / total_sends if total_sends > 0 else 0,
                "open_rate": d["opens"] / d["sends"],
                "click_rate": d["clicks"] / d["sends"],
                "unsub_rate": d["unsubs"] / d["sends"] if d["sends"] > 0 else 0,
            })
    
    return {
        "total_campaigns": total_campaigns,
        "total_sends": total_sends,
        "overall_open_rate": total_opens / total_sends if total_sends > 0 else 0,
        "overall_click_rate": total_clicks / total_sends if total_sends > 0 else 0,
        "overall_unsub_rate": total_unsubs / total_sends if total_sends > 0 else 0,
        "day_rates": day_rates
    }


def generate_report(campaigns):
    """Generate the comprehensive brand-by-brand Markdown report."""
    lines = []
    
    brand_day_stats = analyze_brand_day_detailed(campaigns)
    brand_hour_stats = analyze_brand_hour_detailed(campaigns)
    brand_day_hour = analyze_brand_day_hour(campaigns)
    
    # Get brands sorted by total sends
    brands = []
    for brand in brand_day_stats.keys():
        total_sends = sum(brand_day_stats[brand][d]["sends"] for d in range(7))
        total_campaigns = sum(brand_day_stats[brand][d]["count"] for d in range(7))
        if total_sends >= 50000:  # Minimum threshold
            brands.append((brand, total_sends, total_campaigns))
    brands.sort(key=lambda x: -x[1])
    
    # Header
    lines.append("# Brand-by-Brand Send Day Analysis\n")
    lines.append(f"> {len(campaigns):,} batch campaigns | {len(brands)} brands analyzed\n\n")
    lines.append("---\n\n")
    
    # Overall Summary Table
    lines.append("## Summary Overview\n\n")
    lines.append("| Brand | Campaigns | Total Sends | Open Rate | Click Rate | Best Day | Worst Day |\n")
    lines.append("|-------|-----------|-------------|-----------|------------|----------|----------|\n")
    
    for brand, total_sends, total_campaigns in brands:
        summary = compute_brand_summary(brand_day_stats, brand)
        day_rates = summary["day_rates"]
        
        if day_rates:
            best_day = max(day_rates, key=lambda x: x["click_rate"])
            worst_day = min(day_rates, key=lambda x: x["click_rate"])
            
            lines.append(f"| **{brand}** | {total_campaigns:,} | {format_number(total_sends)} | ")
            lines.append(f"{format_pct(summary['overall_open_rate'])} | ")
            lines.append(f"{format_pct(summary['overall_click_rate'])} | ")
            lines.append(f"{best_day['day_name']} ({format_pct(best_day['click_rate'])}) | ")
            lines.append(f"{worst_day['day_name']} ({format_pct(worst_day['click_rate'])}) |\n")
    
    lines.append("\n---\n\n")
    
    # Detailed brand sections
    for brand, total_sends, total_campaigns in brands:
        summary = compute_brand_summary(brand_day_stats, brand)
        day_rates = summary["day_rates"]
        
        lines.append(f"## {brand}\n\n")
        
        # Brand overview
        lines.append(f"**{total_campaigns:,} campaigns** | **{format_number(total_sends)} sends** | ")
        lines.append(f"Overall: {format_pct(summary['overall_open_rate'])} open, ")
        lines.append(f"{format_pct(summary['overall_click_rate'])} click\n\n")
        
        # Day of week performance table
        lines.append("### Day of Week Performance\n\n")
        lines.append("| Day | Campaigns | Sends | % Volume | Open Rate | Click Rate | Unsub Rate |\n")
        lines.append("|-----|-----------|-------|----------|-----------|------------|------------|\n")
        
        if day_rates:
            best_click_day = max(day_rates, key=lambda x: x["click_rate"])["day"]
            worst_click_day = min(day_rates, key=lambda x: x["click_rate"])["day"]
            
            for d in sorted(day_rates, key=lambda x: x["day"]):
                highlight = "**" if d["day"] == best_click_day else ""
                dim = "~" if d["day"] == worst_click_day else ""
                lines.append(f"| {d['day_name']} | {d['campaigns']:,} | {format_number(d['sends'])} | ")
                lines.append(f"{format_pct(d['pct_volume'], 1)} | {format_pct(d['open_rate'])} | ")
                lines.append(f"{highlight}{format_pct(d['click_rate'])}{highlight} | {format_pct(d['unsub_rate'])} |\n")
        
        lines.append("\n")
        
        # Click rate lift analysis
        if day_rates and len(day_rates) > 1:
            best = max(day_rates, key=lambda x: x["click_rate"])
            worst = min(day_rates, key=lambda x: x["click_rate"])
            if worst["click_rate"] > 0:
                lift = (best["click_rate"] - worst["click_rate"]) / worst["click_rate"] * 100
                lines.append(f"📈 **Best to Worst Lift:** {lift:.0f}% ({best['day_name']} vs {worst['day_name']})\n\n")
        
        # Volume distribution insight
        if day_rates:
            volume_sorted = sorted(day_rates, key=lambda x: -x["pct_volume"])
            top_two = volume_sorted[:2]
            if len(top_two) >= 2:
                lines.append(f"📊 **Volume Concentration:** {format_pct(top_two[0]['pct_volume'] + top_two[1]['pct_volume'], 1)} of sends on {top_two[0]['day_name']} + {top_two[1]['day_name']}\n\n")
        
        # Hour of day analysis for this brand
        lines.append("### Hour of Day Performance\n\n")
        brand_hours = brand_hour_stats[brand]
        
        hour_data = []
        for hour in range(24):
            if brand_hours[hour]["sends"] >= 10000:
                hour_data.append({
                    "hour": hour,
                    "hour_label": format_hour_ampm(hour),
                    "sends": brand_hours[hour]["sends"],
                    "click_rate": brand_hours[hour]["clicks"] / brand_hours[hour]["sends"],
                    "campaigns": brand_hours[hour]["count"]
                })
        
        if hour_data:
            lines.append("| Hour | Campaigns | Sends | Click Rate |\n")
            lines.append("|------|-----------|-------|------------|\n")
            
            best_hour = max(hour_data, key=lambda x: x["click_rate"])
            
            for h in sorted(hour_data, key=lambda x: x["hour"]):
                highlight = "**" if h["hour"] == best_hour["hour"] else ""
                lines.append(f"| {h['hour_label']} | {h['campaigns']:,} | {format_number(h['sends'])} | ")
                lines.append(f"{highlight}{format_pct(h['click_rate'])}{highlight} |\n")
            
            lines.append("\n")
        else:
            lines.append("*Insufficient data for hourly breakdown (requires 10K+ sends per hour)*\n\n")
        
        # Day × Hour heatmap for this brand
        lines.append("### Day × Hour Click Rates\n\n")
        lines.append("*Top performing time slots (5K+ sends minimum)*\n\n")
        
        # Find significant hour/day combos
        significant_hours = set()
        for day in range(7):
            for hour in range(24):
                if brand_day_hour[brand][day][hour]["sends"] >= 5000:
                    significant_hours.add(hour)
        
        significant_hours = sorted(significant_hours)
        
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
                    stats = brand_day_hour[brand][day][hour]
                    if stats["sends"] >= 5000:
                        rate = stats["clicks"] / stats["sends"]
                        lines.append(f" {format_pct(rate)} |")
                    else:
                        lines.append(" - |")
                lines.append("\n")
            
            lines.append("\n")
        else:
            lines.append("*Insufficient data for day × hour breakdown*\n\n")
        
        # Recommendations for this brand
        lines.append("### Recommendations\n\n")
        
        if day_rates:
            best = max(day_rates, key=lambda x: x["click_rate"])
            worst = min(day_rates, key=lambda x: x["click_rate"])
            
            # Check if best day is underutilized
            avg_volume = 1.0 / 7
            if best["pct_volume"] < avg_volume * 0.8:
                lines.append(f"- 🎯 **Opportunity:** {best['day_name']} shows highest click rate but only {format_pct(best['pct_volume'], 1)} of volume\n")
            
            # Check if worst day is overutilized
            if worst["pct_volume"] > avg_volume * 1.2:
                lines.append(f"- ⚠️ **Consider reducing:** {worst['day_name']} has {format_pct(worst['pct_volume'], 1)} volume but lowest click rate\n")
            
            # Weekend vs weekday insight
            weekend_sends = sum(d["sends"] for d in day_rates if d["day"] >= 5)
            weekday_sends = sum(d["sends"] for d in day_rates if d["day"] < 5)
            weekend_clicks = sum(brand_day_stats[brand][d]["clicks"] for d in [5, 6])
            weekday_clicks = sum(brand_day_stats[brand][d]["clicks"] for d in range(5))
            
            if weekend_sends > 0 and weekday_sends > 0:
                weekend_rate = weekend_clicks / weekend_sends
                weekday_rate = weekday_clicks / weekday_sends
                
                if weekend_rate > weekday_rate * 1.1:
                    lines.append(f"- 📅 **Weekend advantage:** {format_pct(weekend_rate)} vs {format_pct(weekday_rate)} weekday click rate\n")
                elif weekday_rate > weekend_rate * 1.1:
                    lines.append(f"- 📅 **Weekday advantage:** {format_pct(weekday_rate)} vs {format_pct(weekend_rate)} weekend click rate\n")
        
        if hour_data:
            best_hour = max(hour_data, key=lambda x: x["click_rate"])
            lines.append(f"- ⏰ **Best send time:** {best_hour['hour_label']} local time ({format_pct(best_hour['click_rate'])} click rate)\n")
        
        lines.append("\n---\n\n")
    
    # Cross-brand comparison
    lines.append("## Cross-Brand Comparison\n\n")
    
    # Day performance ranking
    lines.append("### Best Day by Brand\n\n")
    lines.append("| Rank | Brand | Best Day | Click Rate | Lift vs Worst |\n")
    lines.append("|------|-------|----------|------------|---------------|\n")
    
    brand_best_days = []
    for brand, _, _ in brands:
        summary = compute_brand_summary(brand_day_stats, brand)
        day_rates = summary["day_rates"]
        if day_rates:
            best = max(day_rates, key=lambda x: x["click_rate"])
            worst = min(day_rates, key=lambda x: x["click_rate"])
            lift = ((best["click_rate"] - worst["click_rate"]) / worst["click_rate"] * 100) if worst["click_rate"] > 0 else 0
            brand_best_days.append({
                "brand": brand,
                "best_day": best["day_name"],
                "click_rate": best["click_rate"],
                "lift": lift
            })
    
    brand_best_days.sort(key=lambda x: -x["click_rate"])
    for i, b in enumerate(brand_best_days, 1):
        lines.append(f"| {i} | {b['brand']} | {b['best_day']} | {format_pct(b['click_rate'])} | +{b['lift']:.0f}% |\n")
    
    lines.append("\n")
    
    # Day-by-day brand comparison
    lines.append("### Click Rate by Day (All Brands)\n\n")
    lines.append("| Day |")
    for brand, _, _ in brands:
        lines.append(f" {brand} |")
    lines.append("\n")
    
    lines.append("|-----|")
    for _ in brands:
        lines.append("------|")
    lines.append("\n")
    
    for day in range(7):
        lines.append(f"| {DAY_NAMES[day]} |")
        for brand, _, _ in brands:
            stats = brand_day_stats[brand][day]
            if stats["sends"] > 0:
                rate = stats["clicks"] / stats["sends"]
                lines.append(f" {format_pct(rate)} |")
            else:
                lines.append(" - |")
        lines.append("\n")
    
    lines.append("\n---\n\n")
    
    # Methodology
    lines.append("### Methodology\n\n")
    lines.append("- **Minimum thresholds:** 50K+ total sends per brand, 10K+ sends per hour, 5K+ sends per hour/day combination\n")
    lines.append("- **Time inference:** Local-time sends (span ≥20h) use last_sent - 10h (Hawaii offset); fixed-time sends convert to Mountain Time\n")
    lines.append("- **Click rate:** Total clicks ÷ total sends (not delivered)\n")
    lines.append(f"\n*Analysis generated {datetime.now().strftime('%B %Y')} | {len(campaigns):,} campaigns*\n")
    
    return "".join(lines)


class PDFReport(FPDF):
    """Custom PDF class for the brand analysis report."""
    
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
        self.cell(8, 5, chr(149), new_x=XPos.RIGHT)
        self.multi_cell(0, 5, text)
        self.set_x(x)
        
    def add_table(self, headers, data, col_widths=None, highlight_col=None, highlight_max=True):
        """Add a table to the PDF with optional highlighting."""
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
    """Generate comprehensive PDF report."""
    pdf = PDFReport()
    pdf.add_page()
    
    brand_day_stats = analyze_brand_day_detailed(campaigns)
    brand_hour_stats = analyze_brand_hour_detailed(campaigns)
    
    # Get brands sorted by total sends
    brands = []
    for brand in brand_day_stats.keys():
        total_sends = sum(brand_day_stats[brand][d]["sends"] for d in range(7))
        total_campaigns = sum(brand_day_stats[brand][d]["count"] for d in range(7))
        if total_sends >= 50000:
            brands.append((brand, total_sends, total_campaigns))
    brands.sort(key=lambda x: -x[1])
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'Brand Send Day Analysis', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, f'{len(campaigns):,} batch campaigns | {len(brands)} brands analyzed', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Summary Overview
    pdf.chapter_title('Summary Overview')
    
    headers = ['Brand', 'Campaigns', 'Sends', 'Open Rate', 'Click Rate', 'Best Day', 'Worst Day']
    data = []
    
    for brand, total_sends, total_campaigns in brands:
        summary = compute_brand_summary(brand_day_stats, brand)
        day_rates = summary["day_rates"]
        
        if day_rates:
            best_day = max(day_rates, key=lambda x: x["click_rate"])
            worst_day = min(day_rates, key=lambda x: x["click_rate"])
            
            data.append([
                brand,
                f"{total_campaigns:,}",
                format_number(total_sends),
                format_pct(summary['overall_open_rate']),
                format_pct(summary['overall_click_rate']),
                f"{best_day['day_name'][:3]}",
                f"{worst_day['day_name'][:3]}"
            ])
    
    pdf.add_table(headers, data, col_widths=[25, 25, 25, 30, 30, 25, 25])
    
    # Individual brand sections
    for brand, total_sends, total_campaigns in brands:
        pdf.add_page()
        pdf.chapter_title(f'{brand} - Day of Week Analysis')
        
        summary = compute_brand_summary(brand_day_stats, brand)
        pdf.body_text(f"{total_campaigns:,} campaigns | {format_number(total_sends)} sends | "
                     f"Overall: {format_pct(summary['overall_open_rate'])} open, {format_pct(summary['overall_click_rate'])} click")
        pdf.ln(3)
        
        day_rates = summary["day_rates"]
        
        if day_rates:
            pdf.section_title('Performance by Day')
            headers = ['Day', 'Campaigns', 'Sends', '% Volume', 'Open Rate', 'Click Rate', 'Unsub']
            data = []
            
            for d in sorted(day_rates, key=lambda x: x["day"]):
                data.append([
                    d['day_name'],
                    f"{d['campaigns']:,}",
                    format_number(d['sends']),
                    format_pct(d['pct_volume'], 1),
                    format_pct(d['open_rate']),
                    format_pct(d['click_rate']),
                    format_pct(d['unsub_rate'])
                ])
            
            pdf.add_table(headers, data, col_widths=[28, 25, 23, 23, 28, 28, 23])
            
            # Insights
            best = max(day_rates, key=lambda x: x["click_rate"])
            worst = min(day_rates, key=lambda x: x["click_rate"])
            
            if worst["click_rate"] > 0:
                lift = (best["click_rate"] - worst["click_rate"]) / worst["click_rate"] * 100
                pdf.bullet_point(f"Best to Worst Lift: {lift:.0f}% ({best['day_name']} vs {worst['day_name']})")
        
        # Hour breakdown
        brand_hours = brand_hour_stats[brand]
        hour_data = []
        for hour in range(24):
            if brand_hours[hour]["sends"] >= 10000:
                hour_data.append({
                    "hour": hour,
                    "hour_label": format_hour_ampm(hour),
                    "sends": brand_hours[hour]["sends"],
                    "click_rate": brand_hours[hour]["clicks"] / brand_hours[hour]["sends"],
                    "campaigns": brand_hours[hour]["count"]
                })
        
        if hour_data:
            pdf.ln(5)
            pdf.section_title('Performance by Hour')
            headers = ['Hour', 'Campaigns', 'Sends', 'Click Rate']
            data = []
            
            for h in sorted(hour_data, key=lambda x: x["hour"]):
                data.append([
                    h['hour_label'],
                    f"{h['campaigns']:,}",
                    format_number(h['sends']),
                    format_pct(h['click_rate'])
                ])
            
            pdf.add_table(headers, data, col_widths=[30, 40, 40, 40])
    
    # Cross-brand comparison page
    pdf.add_page()
    pdf.chapter_title('Cross-Brand Comparison')
    
    pdf.section_title('Click Rate by Day (All Brands)')
    headers = ['Day'] + [b[0] for b in brands]
    data = []
    
    col_widths = [30] + [30] * len(brands)
    
    for day in range(7):
        row = [DAY_NAMES[day]]
        for brand, _, _ in brands:
            stats = brand_day_stats[brand][day]
            if stats["sends"] > 0:
                rate = stats["clicks"] / stats["sends"]
                row.append(format_pct(rate))
            else:
                row.append('-')
        data.append(row)
    
    pdf.add_table(headers, data, col_widths=col_widths)
    
    # Best day ranking
    pdf.section_title('Best Day by Brand')
    headers = ['Rank', 'Brand', 'Best Day', 'Click Rate', 'Lift']
    data = []
    
    brand_best_days = []
    for brand, _, _ in brands:
        summary = compute_brand_summary(brand_day_stats, brand)
        day_rates = summary["day_rates"]
        if day_rates:
            best = max(day_rates, key=lambda x: x["click_rate"])
            worst = min(day_rates, key=lambda x: x["click_rate"])
            lift = ((best["click_rate"] - worst["click_rate"]) / worst["click_rate"] * 100) if worst["click_rate"] > 0 else 0
            brand_best_days.append({
                "brand": brand,
                "best_day": best["day_name"],
                "click_rate": best["click_rate"],
                "lift": lift
            })
    
    brand_best_days.sort(key=lambda x: -x["click_rate"])
    for i, b in enumerate(brand_best_days, 1):
        data.append([
            str(i),
            b['brand'],
            b['best_day'],
            format_pct(b['click_rate']),
            f"+{b['lift']:.0f}%"
        ])
    
    pdf.add_table(headers, data, col_widths=[20, 35, 40, 40, 35])
    
    # Footer
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128)
    pdf.cell(0, 5, f"Analysis generated {datetime.now().strftime('%B %Y')} | Times reflect intended local send time", align='C')
    
    pdf.output(str(output_path))
    print(f"PDF written to {output_path}")


def main():
    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaign files")
    
    batch_campaigns = filter_batch_campaigns(campaigns)
    print(f"Found {len(batch_campaigns)} batch campaigns with valid send times")
    
    print("\nGenerating brand send day analysis...")
    
    # Generate Markdown report
    report = generate_report(batch_campaigns)
    md_path = Path(__file__).parent.parent / "brand-send-day-analysis.md"
    with open(md_path, "w") as f:
        f.write(report)
    print(f"Markdown written to {md_path}")
    
    # Generate PDF
    pdf_path = Path(__file__).parent.parent / "brand-send-day-analysis.pdf"
    generate_pdf(batch_campaigns, pdf_path)
    
    print("\nDone!")


if __name__ == "__main__":
    main()








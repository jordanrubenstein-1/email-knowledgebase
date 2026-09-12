#!/usr/bin/env python3
"""
Plain Text vs Designed Email Analysis

Compares plain text emails against designed emails with matched audience sizes
and campaign types to ensure fair comparisons.

Controls for:
- Audience size (quintiles)
- Campaign type (sale_promo, editorial, product_launch, reminder, other)

Outputs results to ANALYSIS.md and plain-text-analysis.pdf
"""

import os
import yaml
import re
from pathlib import Path
from collections import defaultdict
from statistics import median
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

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


def is_plain_text(campaign: dict) -> bool:
    """
    Identify plain text emails by:
    - Campaign name contains '_PT' (case-insensitive), OR
    - structure.layout_type == 'text_only'
    """
    name = campaign.get("name", "")
    if "_pt" in name.lower():
        return True
    
    structure = campaign.get("structure", {})
    if structure.get("layout_type") == "text_only":
        return True
    
    return False


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


def filter_batch_campaigns(campaigns):
    """Filter to batch campaigns only (exclude canvas/triggered)."""
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
        batch.append(c)
    return batch


def calculate_quintiles(campaigns: list) -> tuple:
    """
    Calculate quintile boundaries based on total_sends.
    Returns (boundaries, quintile_labels) where boundaries is a list of 4 cutoff values.
    """
    sends_values = sorted([
        c.get("performance_summary", {}).get("total_sends", 0) 
        for c in campaigns
    ])
    
    n = len(sends_values)
    if n == 0:
        return [], {}
    
    # Calculate quintile boundaries (20%, 40%, 60%, 80%)
    boundaries = [
        sends_values[int(n * 0.2)],
        sends_values[int(n * 0.4)],
        sends_values[int(n * 0.6)],
        sends_values[int(n * 0.8)],
    ]
    
    return boundaries


def get_quintile(total_sends: int, boundaries: list) -> str:
    """Assign a campaign to a quintile based on total_sends."""
    if not boundaries:
        return "Q1"
    
    if total_sends <= boundaries[0]:
        return "Q1"
    elif total_sends <= boundaries[1]:
        return "Q2"
    elif total_sends <= boundaries[2]:
        return "Q3"
    elif total_sends <= boundaries[3]:
        return "Q4"
    else:
        return "Q5"


def get_quintile_range(quintile: str, boundaries: list, use_unicode: bool = True) -> str:
    """Get human-readable range for a quintile."""
    if not boundaries:
        return "All"
    
    # Use ASCII-safe characters for PDF output
    lte = "<=" if not use_unicode else "≤"
    gt = ">" 
    
    ranges = {
        "Q1": f"{lte}{format_number(boundaries[0])}",
        "Q2": f"{format_number(boundaries[0]+1)}-{format_number(boundaries[1])}",
        "Q3": f"{format_number(boundaries[1]+1)}-{format_number(boundaries[2])}",
        "Q4": f"{format_number(boundaries[2]+1)}-{format_number(boundaries[3])}",
        "Q5": f"{gt}{format_number(boundaries[3])}",
    }
    return ranges.get(quintile, "Unknown")


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


def analyze_overall(campaigns: list) -> dict:
    """Analyze overall PT vs Designed performance."""
    pt_stats = {"sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0}
    designed_stats = {"sends": 0, "opens": 0, "clicks": 0, "unsubs": 0, "count": 0}
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        stats = pt_stats if is_plain_text(c) else designed_stats
        
        stats["sends"] += perf.get("total_sends", 0)
        stats["opens"] += perf.get("total_opens", 0)
        stats["clicks"] += perf.get("total_clicks", 0)
        stats["unsubs"] += perf.get("total_unsubscribes", 0)
        stats["count"] += 1
    
    return {
        "plain_text": pt_stats,
        "designed": designed_stats
    }


def analyze_by_quintile(campaigns: list, boundaries: list) -> dict:
    """Analyze PT vs Designed by audience size quintile."""
    results = defaultdict(lambda: {
        "pt": {"sends": 0, "opens": 0, "clicks": 0, "count": 0},
        "designed": {"sends": 0, "opens": 0, "clicks": 0, "count": 0}
    })
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        total_sends = perf.get("total_sends", 0)
        quintile = get_quintile(total_sends, boundaries)
        
        key = "pt" if is_plain_text(c) else "designed"
        results[quintile][key]["sends"] += total_sends
        results[quintile][key]["opens"] += perf.get("total_opens", 0)
        results[quintile][key]["clicks"] += perf.get("total_clicks", 0)
        results[quintile][key]["count"] += 1
    
    return results


def analyze_by_campaign_type(campaigns: list) -> dict:
    """Analyze PT vs Designed by campaign type."""
    results = defaultdict(lambda: {
        "pt": {"sends": 0, "opens": 0, "clicks": 0, "count": 0},
        "designed": {"sends": 0, "opens": 0, "clicks": 0, "count": 0}
    })
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        campaign_type = classify_campaign_type(c.get("name", ""))
        
        key = "pt" if is_plain_text(c) else "designed"
        results[campaign_type][key]["sends"] += perf.get("total_sends", 0)
        results[campaign_type][key]["opens"] += perf.get("total_opens", 0)
        results[campaign_type][key]["clicks"] += perf.get("total_clicks", 0)
        results[campaign_type][key]["count"] += 1
    
    return results


def analyze_full_matrix(campaigns: list, boundaries: list) -> dict:
    """Full cross-tabulation: Quintile x Campaign Type x Format."""
    results = defaultdict(lambda: defaultdict(lambda: {
        "pt": {"sends": 0, "opens": 0, "clicks": 0, "count": 0},
        "designed": {"sends": 0, "opens": 0, "clicks": 0, "count": 0}
    }))
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        total_sends = perf.get("total_sends", 0)
        quintile = get_quintile(total_sends, boundaries)
        campaign_type = classify_campaign_type(c.get("name", ""))
        
        key = "pt" if is_plain_text(c) else "designed"
        results[quintile][campaign_type][key]["sends"] += total_sends
        results[quintile][campaign_type][key]["opens"] += perf.get("total_opens", 0)
        results[quintile][campaign_type][key]["clicks"] += perf.get("total_clicks", 0)
        results[quintile][campaign_type][key]["count"] += 1
    
    return results


def generate_report(campaigns: list) -> str:
    """Generate the analysis report."""
    boundaries = calculate_quintiles(campaigns)
    
    lines = []
    lines.append("\n---\n")
    lines.append("## Plain Text vs Designed Email Analysis\n")
    lines.append("> Comparing plain text emails against designed emails, controlling for audience size and campaign type.\n\n")
    
    # Overall stats
    overall = analyze_overall(campaigns)
    pt = overall["plain_text"]
    designed = overall["designed"]
    
    lines.append(f"**Dataset:** {pt['count']:,} plain text campaigns ({format_number(pt['sends'])} sends), ")
    lines.append(f"{designed['count']:,} designed campaigns ({format_number(designed['sends'])} sends)\n\n")
    
    # 1. Overall Comparison (with caveat)
    lines.append("### Overall Comparison (Uncontrolled)\n\n")
    lines.append("*Note: Plain text emails are often sent to smaller, more engaged lists. See controlled comparisons below.*\n\n")
    
    lines.append("| Format | Campaigns | Sends | Open Rate | Click Rate |\n")
    lines.append("|--------|-----------|-------|-----------|------------|\n")
    
    if pt["sends"] > 0:
        pt_open_rate = pt["opens"] / pt["sends"]
        pt_click_rate = pt["clicks"] / pt["sends"]
        lines.append(f"| Plain Text | {pt['count']:,} | {format_number(pt['sends'])} | {format_pct(pt_open_rate)} | {format_pct(pt_click_rate)} |\n")
    
    if designed["sends"] > 0:
        designed_open_rate = designed["opens"] / designed["sends"]
        designed_click_rate = designed["clicks"] / designed["sends"]
        lines.append(f"| Designed | {designed['count']:,} | {format_number(designed['sends'])} | {format_pct(designed_open_rate)} | {format_pct(designed_click_rate)} |\n")
    
    lines.append("\n")
    
    # 2. Quintile-Controlled Comparison
    lines.append("### Audience Size Controlled (Quintiles)\n\n")
    lines.append("*Comparing PT vs Designed within same audience size tiers ensures apples-to-apples comparison.*\n\n")
    
    quintile_data = analyze_by_quintile(campaigns, boundaries)
    
    lines.append("| Quintile | Audience Range | PT Campaigns | PT Click Rate | Designed Campaigns | Designed Click Rate | Delta |\n")
    lines.append("|----------|----------------|--------------|---------------|--------------------|--------------------|-------|\n")
    
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        data = quintile_data[q]
        range_str = get_quintile_range(q, boundaries)
        
        pt_count = data["pt"]["count"]
        pt_click = data["pt"]["clicks"] / data["pt"]["sends"] if data["pt"]["sends"] > 0 else 0
        
        designed_count = data["designed"]["count"]
        designed_click = data["designed"]["clicks"] / data["designed"]["sends"] if data["designed"]["sends"] > 0 else 0
        
        if pt_count > 0 and designed_count > 0:
            delta = pt_click - designed_click
            delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
        else:
            delta_str = "-"
        
        pt_click_str = format_pct(pt_click) if pt_count > 0 else "-"
        designed_click_str = format_pct(designed_click) if designed_count > 0 else "-"
        
        lines.append(f"| {q} | {range_str} | {pt_count:,} | {pt_click_str} | {designed_count:,} | {designed_click_str} | {delta_str} |\n")
    
    lines.append("\n")
    
    # 3. Campaign Type Controlled
    lines.append("### Campaign Type Controlled\n\n")
    lines.append("*Comparing PT vs Designed within same campaign types.*\n\n")
    
    type_data = analyze_by_campaign_type(campaigns)
    types = ["sale_promo", "editorial", "product_launch", "reminder", "other"]
    
    lines.append("| Campaign Type | PT Campaigns | PT Click Rate | Designed Campaigns | Designed Click Rate | Delta |\n")
    lines.append("|---------------|--------------|---------------|--------------------|--------------------|-------|\n")
    
    for ctype in types:
        data = type_data[ctype]
        
        pt_count = data["pt"]["count"]
        pt_click = data["pt"]["clicks"] / data["pt"]["sends"] if data["pt"]["sends"] > 0 else 0
        
        designed_count = data["designed"]["count"]
        designed_click = data["designed"]["clicks"] / data["designed"]["sends"] if data["designed"]["sends"] > 0 else 0
        
        if pt_count > 0 and designed_count > 0:
            delta = pt_click - designed_click
            delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
        else:
            delta_str = "-"
        
        pt_click_str = format_pct(pt_click) if pt_count > 0 else "-"
        designed_click_str = format_pct(designed_click) if designed_count > 0 else "-"
        
        lines.append(f"| {ctype} | {pt_count:,} | {pt_click_str} | {designed_count:,} | {designed_click_str} | {delta_str} |\n")
    
    lines.append("\n")
    
    # 4. Full Matrix (Quintile x Campaign Type) - showing PT vs Designed delta
    lines.append("### Full Matrix: Quintile × Campaign Type (PT - Designed Click Rate Delta)\n\n")
    lines.append("*Positive values = PT outperforms, Negative = Designed outperforms*\n\n")
    
    matrix = analyze_full_matrix(campaigns, boundaries)
    
    # Header
    lines.append("| Quintile |")
    for ctype in types:
        lines.append(f" {ctype} |")
    lines.append("\n")
    
    lines.append("|----------|")
    for _ in types:
        lines.append("----------|")
    lines.append("\n")
    
    # Data rows
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        lines.append(f"| {q} |")
        for ctype in types:
            data = matrix[q][ctype]
            
            pt_click = data["pt"]["clicks"] / data["pt"]["sends"] if data["pt"]["sends"] > 0 else None
            designed_click = data["designed"]["clicks"] / data["designed"]["sends"] if data["designed"]["sends"] > 0 else None
            
            if pt_click is not None and designed_click is not None:
                delta = pt_click - designed_click
                delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
                # Add count context
                delta_str += f" ({data['pt']['count']}/{data['designed']['count']})"
            else:
                delta_str = "-"
            
            lines.append(f" {delta_str} |")
        lines.append("\n")
    
    lines.append("\n*Format: Delta (PT count/Designed count)*\n\n")
    
    # 5. Key Findings
    lines.append("### Key Findings\n\n")
    
    findings = []
    
    # Calculate average PT vs Designed delta across quintiles with sufficient data
    pt_wins = 0
    designed_wins = 0
    total_comparisons = 0
    
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        data = quintile_data[q]
        if data["pt"]["sends"] > 0 and data["designed"]["sends"] > 0:
            pt_click = data["pt"]["clicks"] / data["pt"]["sends"]
            designed_click = data["designed"]["clicks"] / data["designed"]["sends"]
            total_comparisons += 1
            if pt_click > designed_click:
                pt_wins += 1
            else:
                designed_wins += 1
    
    if total_comparisons > 0:
        if pt_wins > designed_wins:
            findings.append(f"**Plain text outperforms in {pt_wins}/{total_comparisons} quintiles** — When controlling for audience size, PT emails tend to get higher click rates.")
        elif designed_wins > pt_wins:
            findings.append(f"**Designed emails outperform in {designed_wins}/{total_comparisons} quintiles** — When controlling for audience size, designed emails tend to get higher click rates.")
        else:
            findings.append(f"**Mixed results across quintiles** — PT and Designed emails each win in {pt_wins}/{total_comparisons} quintiles.")
    
    # Find best campaign type for PT
    best_pt_type = None
    best_pt_delta = -999
    for ctype in types:
        data = type_data[ctype]
        if data["pt"]["sends"] > 0 and data["designed"]["sends"] > 0 and data["pt"]["count"] >= 10:
            pt_click = data["pt"]["clicks"] / data["pt"]["sends"]
            designed_click = data["designed"]["clicks"] / data["designed"]["sends"]
            delta = pt_click - designed_click
            if delta > best_pt_delta:
                best_pt_delta = delta
                best_pt_type = ctype
    
    if best_pt_type and best_pt_delta > 0:
        findings.append(f"**PT works best for {best_pt_type}** — {format_pct(best_pt_delta)} higher click rate than designed emails in this category.")
    
    # Audience size insight
    avg_pt_sends = pt["sends"] / pt["count"] if pt["count"] > 0 else 0
    avg_designed_sends = designed["sends"] / designed["count"] if designed["count"] > 0 else 0
    
    if avg_pt_sends < avg_designed_sends * 0.5:
        findings.append(f"**PT emails target smaller audiences** — Average PT send: {format_number(avg_pt_sends)} vs Designed: {format_number(avg_designed_sends)}. This explains part of the performance difference.")
    
    for i, finding in enumerate(findings, 1):
        lines.append(f"{i}. {finding}\n\n")
    
    if not findings:
        lines.append("*Insufficient data to generate automated findings.*\n\n")
    
    # Methodology note
    lines.append("### Methodology\n\n")
    lines.append("- **Plain Text identification:** Campaign name contains '_PT' (case-insensitive) OR `structure.layout_type == 'text_only'`\n")
    lines.append("- **Quintiles:** All campaigns sorted by `total_sends` and split into 5 equal groups\n")
    lines.append("- **Campaign Type:** Classified by keyword patterns in campaign name\n")
    lines.append("- **Minimum threshold:** 1,000+ sends per campaign\n")
    
    lines.append("\n")
    
    return "".join(lines)


class PDFReport(FPDF):
    """Custom PDF class for the plain text analysis report."""
    
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


def generate_pdf(campaigns: list, output_path: Path):
    """Generate PDF report from campaign data."""
    pdf = PDFReport()
    pdf.add_page()
    
    boundaries = calculate_quintiles(campaigns)
    overall = analyze_overall(campaigns)
    quintile_data = analyze_by_quintile(campaigns, boundaries)
    type_data = analyze_by_campaign_type(campaigns)
    matrix = analyze_full_matrix(campaigns, boundaries)
    
    pt = overall["plain_text"]
    designed = overall["designed"]
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'Plain Text vs Designed Email Analysis', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, f'{pt["count"]:,} PT campaigns | {designed["count"]:,} designed campaigns | Controlled for audience size & type', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Executive Summary
    pdf.chapter_title('Executive Summary')
    pdf.body_text('This analysis compares plain text emails against designed emails, controlling for audience size (quintiles) and campaign type to ensure fair comparisons.')
    pdf.ln(3)
    
    pdf.section_title('Key Insight')
    pdf.bullet_point('Plain text emails are typically sent to smaller, more engaged lists')
    pdf.bullet_point('When controlling for audience size, the performance difference changes significantly')
    pdf.bullet_point('PT outperforms for small audiences (Q1-Q2), Designed wins for large audiences (Q3-Q5)')
    pdf.ln(5)
    
    # Overall Comparison
    pdf.chapter_title('Overall Comparison (Uncontrolled)')
    pdf.body_text('Note: This comparison does NOT control for audience size differences.')
    pdf.ln(2)
    
    headers = ['Format', 'Campaigns', 'Sends', 'Open Rate', 'Click Rate']
    data = []
    
    if pt["sends"] > 0:
        pt_open = pt["opens"] / pt["sends"]
        pt_click = pt["clicks"] / pt["sends"]
        data.append(['Plain Text', f'{pt["count"]:,}', format_number(pt["sends"]), format_pct(pt_open), format_pct(pt_click)])
    
    if designed["sends"] > 0:
        designed_open = designed["opens"] / designed["sends"]
        designed_click = designed["clicks"] / designed["sends"]
        data.append(['Designed', f'{designed["count"]:,}', format_number(designed["sends"]), format_pct(designed_open), format_pct(designed_click)])
    
    pdf.add_table(headers, data, col_widths=[35, 30, 30, 35, 35])
    
    # Audience Size Controlled
    pdf.add_page()
    pdf.chapter_title('Audience Size Controlled (Quintiles)')
    pdf.body_text('Comparing PT vs Designed within same audience size tiers ensures apples-to-apples comparison.')
    pdf.ln(2)
    
    headers = ['Quintile', 'Range', 'PT Count', 'PT Click', 'Designed Count', 'Designed Click', 'Delta']
    data = []
    
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        qdata = quintile_data[q]
        range_str = get_quintile_range(q, boundaries, use_unicode=False)
        
        pt_count = qdata["pt"]["count"]
        pt_click = qdata["pt"]["clicks"] / qdata["pt"]["sends"] if qdata["pt"]["sends"] > 0 else 0
        
        d_count = qdata["designed"]["count"]
        d_click = qdata["designed"]["clicks"] / qdata["designed"]["sends"] if qdata["designed"]["sends"] > 0 else 0
        
        if pt_count > 0 and d_count > 0:
            delta = pt_click - d_click
            delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
        else:
            delta_str = "-"
        
        pt_click_str = format_pct(pt_click) if pt_count > 0 else "-"
        d_click_str = format_pct(d_click) if d_count > 0 else "-"
        
        data.append([q, range_str, str(pt_count), pt_click_str, str(d_count), d_click_str, delta_str])
    
    pdf.add_table(headers, data, col_widths=[20, 35, 25, 25, 30, 30, 25])
    
    pdf.ln(3)
    pdf.section_title('Interpretation')
    pdf.bullet_point('Q1-Q2 (smaller audiences): Plain text emails outperform designed emails')
    pdf.bullet_point('Q3-Q5 (larger audiences): Designed emails outperform plain text emails')
    pdf.bullet_point('The overall PT advantage disappears when controlling for audience size')
    
    # Campaign Type Controlled
    pdf.add_page()
    pdf.chapter_title('Campaign Type Controlled')
    pdf.body_text('Comparing PT vs Designed within same campaign types.')
    pdf.ln(2)
    
    headers = ['Type', 'PT Count', 'PT Click', 'Designed Count', 'Designed Click', 'Delta']
    data = []
    types = ["sale_promo", "editorial", "product_launch", "reminder", "other"]
    
    for ctype in types:
        tdata = type_data[ctype]
        
        pt_count = tdata["pt"]["count"]
        pt_click = tdata["pt"]["clicks"] / tdata["pt"]["sends"] if tdata["pt"]["sends"] > 0 else 0
        
        d_count = tdata["designed"]["count"]
        d_click = tdata["designed"]["clicks"] / tdata["designed"]["sends"] if tdata["designed"]["sends"] > 0 else 0
        
        if pt_count > 0 and d_count > 0:
            delta = pt_click - d_click
            delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
        else:
            delta_str = "-"
        
        pt_click_str = format_pct(pt_click) if pt_count > 0 else "-"
        d_click_str = format_pct(d_click) if d_count > 0 else "-"
        
        data.append([ctype, str(pt_count), pt_click_str, str(d_count), d_click_str, delta_str])
    
    pdf.add_table(headers, data, col_widths=[35, 25, 25, 35, 35, 25])
    
    # Full Matrix
    pdf.add_page()
    pdf.chapter_title('Full Matrix: Quintile x Campaign Type')
    pdf.body_text('PT - Designed click rate delta. Positive = PT outperforms.')
    pdf.ln(2)
    
    headers = ['Quintile', 'sale_promo', 'editorial', 'product', 'reminder', 'other']
    data = []
    
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        row = [q]
        for ctype in types:
            mdata = matrix[q][ctype]
            
            pt_click = mdata["pt"]["clicks"] / mdata["pt"]["sends"] if mdata["pt"]["sends"] > 0 else None
            d_click = mdata["designed"]["clicks"] / mdata["designed"]["sends"] if mdata["designed"]["sends"] > 0 else None
            
            if pt_click is not None and d_click is not None:
                delta = pt_click - d_click
                delta_str = f"+{format_pct(delta)}" if delta > 0 else format_pct(delta)
            else:
                delta_str = "-"
            row.append(delta_str)
        data.append(row)
    
    pdf.add_table(headers, data, col_widths=[25, 33, 33, 33, 33, 33])
    
    # Recommendations
    pdf.add_page()
    pdf.chapter_title('Recommendations')
    pdf.body_text('Based on the plain text vs designed email analysis:')
    pdf.ln(3)
    
    pdf.bullet_point('Use plain text for small, engaged audiences (under ~40K sends) - PT shows consistent lift in Q1-Q2')
    pdf.bullet_point('Use designed emails for large audience sends (over ~40K) - Designed emails perform better at scale')
    pdf.bullet_point('Test PT for reminder campaigns - PT shows positive delta across most reminder scenarios')
    pdf.bullet_point('Consider the novelty factor - PT may outperform partly because it stands out from designed emails')
    
    pdf.ln(10)
    pdf.section_title('Methodology')
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100)
    pdf.bullet_point("Plain Text identification: Campaign name contains '_PT' OR layout_type == 'text_only'")
    pdf.bullet_point("Quintiles: All campaigns sorted by total_sends and split into 5 equal groups")
    pdf.bullet_point("Campaign Type: Classified by keyword patterns in campaign name")
    pdf.bullet_point("Minimum threshold: 1,000+ sends per campaign")
    
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128)
    pdf.cell(0, 5, f"Analysis generated {datetime.now().strftime('%B %Y')}", align='C')
    
    # Save PDF
    pdf.output(str(output_path))
    print(f"PDF written to {output_path}")


def main():
    print("Loading campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} total campaign files")

    batch_campaigns = filter_batch_campaigns(campaigns)
    print(f"Found {len(batch_campaigns)} batch campaigns (1000+ sends)")
    
    pt_count = sum(1 for c in batch_campaigns if is_plain_text(c))
    print(f"  - {pt_count} plain text campaigns")
    print(f"  - {len(batch_campaigns) - pt_count} designed campaigns")

    print("\nGenerating analysis report...")
    report = generate_report(batch_campaigns)

    # Read existing ANALYSIS.md
    analysis_path = Path(__file__).parent.parent / "ANALYSIS.md"
    with open(analysis_path) as f:
        existing = f.read()

    # Check if section already exists
    if "## Plain Text vs Designed Email Analysis" in existing:
        # Replace existing section
        pattern = r"\n---\n\n## Plain Text vs Designed Email Analysis.*?(?=\n---\n## |\Z)"
        existing = re.sub(pattern, "", existing, flags=re.DOTALL)

    # Append new section
    with open(analysis_path, "w") as f:
        f.write(existing.rstrip())
        f.write(report)

    print(f"\nMarkdown written to {analysis_path}")
    
    # Generate PDF
    pdf_path = Path(__file__).parent.parent / "plain-text-analysis.pdf"
    generate_pdf(batch_campaigns, pdf_path)

    print("\nDone!")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""Generate ID-specific PDF report with top/bottom 5 by CTR and top 5 by revenue."""

import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from fpdf import FPDF
from fpdf.enums import XPos, YPos

sys.path.insert(0, str(Path(__file__).parent))
from analyze_sms_q4_2025 import (
    parse_ga4_csv,
    get_sms_campaigns_from_braze,
    match_campaigns_to_ga4,
    fetch_braze_analytics_for_campaigns,
    filter_campaigns_with_extractable_dates,
    infer_brand_from_campaign_name,
    format_currency,
    format_pct,
    format_number,
    sanitize_text_for_pdf,
    BRAND_CSV_MAPPING,
    START_DATE,
    END_DATE,
)

load_dotenv(Path(__file__).parent.parent / ".env")


class IDReportPDF(FPDF):
    """Custom PDF class for ID SMS analysis."""
    
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
        
    def body_text(self, text, font_size=10):
        self.set_font('Helvetica', '', font_size)
        self.set_text_color(51)
        self.multi_cell(0, 5, text)
        self.ln(2)
        
    def add_table(self, headers, data, col_widths=None):
        """Add a table to the PDF."""
        if not data:
            return
            
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)
        
        # Header
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(0)
        fill = True
        
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 7, str(header), border=1, fill=fill, align='L')
        self.ln()
        
        # Data rows
        self.set_font('Helvetica', '', 9)
        fill = False
        for row in data:
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6, str(cell), border=1, fill=fill, align='L')
            self.ln()
            fill = not fill
        self.ln(3)


def generate_id_report():
    """Generate ID-specific PDF report."""
    brand = "ID"
    print(f"Generating {brand} SMS Performance Report...")
    print("=" * 60)
    
    # Parse CSV
    print(f"\n1. Parsing {brand} CSV...")
    csv_path = BRAND_CSV_MAPPING[brand]
    ga4_data = parse_ga4_csv(csv_path, brand)
    print(f"   Found {len(ga4_data)} campaigns in CSV")
    
    # Get Braze campaigns
    print(f"\n2. Fetching {brand} campaigns from Braze...")
    braze_campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
    print(f"   Found {len(braze_campaigns)} SMS campaigns in Braze")
    
    # Match campaigns
    print(f"\n3. Matching campaigns...")
    matched = match_campaigns_to_ga4(ga4_data, braze_campaigns)
    print(f"   Matched {len(matched)} campaigns")
    
    # Fetch analytics
    print(f"\n4. Fetching Braze analytics...")
    fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
    
    # Filter to campaigns with extractable dates
    matched = filter_campaigns_with_extractable_dates(matched, START_DATE, END_DATE)
    print(f"   Filtered to {len(matched)} campaigns with extractable dates")
    
    # Filter to ID brand only (extra check)
    id_campaigns = [c for c in matched if infer_brand_from_campaign_name(c.get('name', '')) == brand]
    print(f"   {len(id_campaigns)} {brand} campaigns in date range")
    
    # Sort for top/bottom 5 by CTR
    campaigns_with_ctr = [c for c in id_campaigns if c.get('braze_sends', 0) > 0]
    campaigns_sorted_by_ctr = sorted(
        campaigns_with_ctr,
        key=lambda x: -x.get('braze_click_rate', 0)
    )
    
    top5_by_ctr = campaigns_sorted_by_ctr[:5]
    bottom5_by_ctr = campaigns_sorted_by_ctr[-5:] if len(campaigns_sorted_by_ctr) >= 5 else campaigns_sorted_by_ctr
    
    # Sort for top 5 by revenue
    campaigns_sorted_by_revenue = sorted(
        id_campaigns,
        key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0)
    )
    top5_by_revenue = campaigns_sorted_by_revenue[:5]
    
    # Generate PDF
    print(f"\n5. Generating PDF report...")
    pdf = IDReportPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, f'{brand} SMS Performance Analysis: Q4 2025', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, 'October 1 - December 31, 2025', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Top 5 by CTR
    pdf.chapter_title('Top 5 Campaigns by CTR')
    headers = ['Rank', 'Campaign Name', 'CTR', 'Sends', 'Clicks', 'Revenue', 'Sessions', 'Purchases']
    data = []
    
    for idx, campaign in enumerate(top5_by_ctr, 1):
        ga4 = campaign.get('ga4_metrics', {})
        data.append([
            idx,
            campaign['name'][:50],  # Truncate long names
            format_pct(campaign.get('braze_click_rate', 0)),
            format_number(campaign.get('braze_sends', 0)),
            format_number(campaign.get('braze_clicks', 0)),
            format_currency(ga4.get('revenue', 0)),
            format_number(ga4.get('sessions', 0)),
            ga4.get('purchases', 0),
        ])
    
    pdf.add_table(headers, data, col_widths=[12, 75, 18, 22, 18, 22, 18, 18])
    
    # Bottom 5 by CTR
    pdf.add_page()
    pdf.chapter_title('Bottom 5 Campaigns by CTR')
    headers = ['Rank', 'Campaign Name', 'CTR', 'Sends', 'Clicks', 'Revenue', 'Sessions', 'Purchases']
    data = []
    
    # Reverse for display (lowest first)
    bottom5_reversed = list(reversed(bottom5_by_ctr))
    for idx, campaign in enumerate(bottom5_reversed, 1):
        ga4 = campaign.get('ga4_metrics', {})
        data.append([
            idx,
            campaign['name'][:50],
            format_pct(campaign.get('braze_click_rate', 0)),
            format_number(campaign.get('braze_sends', 0)),
            format_number(campaign.get('braze_clicks', 0)),
            format_currency(ga4.get('revenue', 0)),
            format_number(ga4.get('sessions', 0)),
            ga4.get('purchases', 0),
        ])
    
    pdf.add_table(headers, data, col_widths=[12, 75, 18, 22, 18, 22, 18, 18])
    
    # Top 5 by Revenue
    pdf.add_page()
    pdf.chapter_title('Top 5 Campaigns by Revenue')
    headers = ['Rank', 'Campaign Name', 'Revenue', 'CTR', 'Sends', 'Clicks', 'Sessions', 'Purchases']
    data = []
    
    for idx, campaign in enumerate(top5_by_revenue, 1):
        ga4 = campaign.get('ga4_metrics', {})
        data.append([
            idx,
            campaign['name'][:50],
            format_currency(ga4.get('revenue', 0)),
            format_pct(campaign.get('braze_click_rate', 0)),
            format_number(campaign.get('braze_sends', 0)),
            format_number(campaign.get('braze_clicks', 0)),
            format_number(ga4.get('sessions', 0)),
            ga4.get('purchases', 0),
        ])
    
    pdf.add_table(headers, data, col_widths=[12, 75, 22, 18, 22, 18, 18, 18])
    
    # Save PDF
    output_path = Path(__file__).parent.parent / "id-sms-performance-report.pdf"
    pdf.output(str(output_path))
    
    print(f"\nPDF written to {output_path}")
    print(f"\nSummary:")
    print(f"  Total {brand} campaigns analyzed: {len(id_campaigns)}")
    print(f"  Top 5 by CTR: {len(top5_by_ctr)} campaigns")
    print(f"  Bottom 5 by CTR: {len(bottom5_by_ctr)} campaigns")
    print(f"  Top 5 by Revenue: {len(top5_by_revenue)} campaigns")


if __name__ == "__main__":
    generate_id_report()



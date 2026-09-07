#!/usr/bin/env python3
"""Generate PDF report with top 5 P_ campaigns by revenue and top/bottom 5 by CTR across all brands."""

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


class PCampaignsReportPDF(FPDF):
    """Custom PDF class for P_ campaigns analysis."""
    
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


def categorize_campaign_type(campaign_name):
    """Categorize campaign as TRG_, P_, or Other."""
    if not campaign_name:
        return 'Other'
    name_upper = campaign_name.upper()
    if name_upper.startswith('TRG_'):
        return 'TRG_'
    elif name_upper.startswith('P_'):
        return 'P_'
    return 'Other'


def generate_p_campaigns_report():
    """Generate PDF report for P_ campaigns across all brands."""
    print("Generating P_ Campaigns Performance Report...")
    print("=" * 60)
    
    # Collect all P_ campaigns from all brands
    all_p_campaigns = []
    
    for brand in BRAND_CSV_MAPPING.keys():
        if brand == "TI":
            continue
        
        print(f"\nProcessing {brand}...")
        csv_path = BRAND_CSV_MAPPING[brand]
        ga4_data = parse_ga4_csv(csv_path, brand)
        print(f"  Found {len(ga4_data)} campaigns in CSV")
        
        # Filter to only P_ campaigns (exclude TRG_)
        ga4_p = {name: metrics for name, metrics in ga4_data.items() 
                 if categorize_campaign_type(name) == 'P_'}
        print(f"  P_ campaigns in CSV: {len(ga4_p)}")
        
        # Get Braze campaigns
        braze_campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
        print(f"  Found {len(braze_campaigns)} SMS campaigns in Braze")
        
        # Match campaigns
        matched = match_campaigns_to_ga4(ga4_p, braze_campaigns)
        print(f"  Matched {len(matched)} campaigns")
        
        # Fetch analytics
        fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
        
        # Add brand metadata
        for campaign in matched:
            campaign['brand'] = infer_brand_from_campaign_name(campaign.get('name', ''))
        
        all_p_campaigns.extend(matched)
    
    # Filter to campaigns with extractable dates
    all_p_campaigns = filter_campaigns_with_extractable_dates(all_p_campaigns, START_DATE, END_DATE)
    print(f"\nTotal P_ campaigns with extractable dates: {len(all_p_campaigns)}")
    
    # Group campaigns by brand
    from collections import defaultdict
    campaigns_by_brand = defaultdict(list)
    for campaign in all_p_campaigns:
        brand = campaign.get('brand') or 'Unknown'
        campaigns_by_brand[brand].append(campaign)
    
    # Generate PDF
    print(f"\nGenerating PDF report...")
    pdf = PCampaignsReportPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'P_ Campaigns Performance Analysis: Q4 2025', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, 'October 1 - December 31, 2025 | By Brand', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Process each brand (sort with None handling)
    for brand in sorted(campaigns_by_brand.keys(), key=lambda x: (x is None, x or '')):
        brand_campaigns = campaigns_by_brand[brand]
        print(f"  Processing {brand}: {len(brand_campaigns)} campaigns")
        
        # Sort for top/bottom 5 by revenue
        campaigns_sorted_by_revenue = sorted(
            brand_campaigns,
            key=lambda x: -x.get('ga4_metrics', {}).get('revenue', 0)
        )
        top5_by_revenue = campaigns_sorted_by_revenue[:5]
        bottom5_by_revenue = campaigns_sorted_by_revenue[-5:] if len(campaigns_sorted_by_revenue) >= 5 else campaigns_sorted_by_revenue
        
        # Sort for top/bottom 5 by CTR (only campaigns with sends > 0)
        campaigns_with_ctr = [c for c in brand_campaigns if c.get('braze_sends', 0) > 0]
        campaigns_sorted_by_ctr = sorted(
            campaigns_with_ctr,
            key=lambda x: -x.get('braze_click_rate', 0)
        )
        top5_by_ctr = campaigns_sorted_by_ctr[:5] if len(campaigns_sorted_by_ctr) >= 5 else campaigns_sorted_by_ctr
        bottom5_by_ctr = campaigns_sorted_by_ctr[-5:] if len(campaigns_sorted_by_ctr) >= 5 else campaigns_sorted_by_ctr
        
        # Brand header
        pdf.add_page()
        pdf.set_font('Helvetica', 'B', 20)
        pdf.set_text_color(44, 62, 80)
        pdf.cell(0, 12, f'{brand} Brand', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(5)
        
        # Brand summary
        brand_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in brand_campaigns)
        brand_sends = sum(c.get('braze_sends', 0) for c in brand_campaigns)
        brand_clicks = sum(c.get('braze_clicks', 0) for c in brand_campaigns)
        brand_avg_ctr = (brand_clicks / brand_sends * 100) if brand_sends > 0 else 0
        
        pdf.section_title(f'{brand} Summary')
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 6, f'Total P_ Campaigns: {len(brand_campaigns)}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f'Total Revenue: {format_currency(brand_revenue)}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f'Total Sends: {format_number(brand_sends)}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f'Total Clicks: {format_number(brand_clicks)}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f'Average CTR: {format_pct(brand_avg_ctr / 100)}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(8)
        
        # Top 5 by Revenue
        pdf.section_title(f'{brand} - Top 5 by Revenue')
        headers = ['Rank', 'Campaign Name', 'Revenue', 'CTR', 'Sends', 'Clicks', 'Sessions', 'Purchases']
        data = []
        
        for idx, campaign in enumerate(top5_by_revenue, 1):
            ga4 = campaign.get('ga4_metrics', {})
            campaign_name = campaign['name']
            # Truncate very long names
            if len(campaign_name) > 50:
                campaign_name = campaign_name[:47] + "..."
            
            data.append([
                idx,
                campaign_name,
                format_currency(ga4.get('revenue', 0)),
                format_pct(campaign.get('braze_click_rate', 0)),
                format_number(campaign.get('braze_sends', 0)),
                format_number(campaign.get('braze_clicks', 0)),
                format_number(ga4.get('sessions', 0)),
                ga4.get('purchases', 0),
            ])
        
        if data:
            pdf.add_table(headers, data, col_widths=[12, 85, 22, 15, 18, 15, 15, 15])
        else:
            pdf.body_text("No campaigns with revenue data.")
        pdf.ln(5)
        
        # Bottom 5 by Revenue
        pdf.section_title(f'{brand} - Bottom 5 by Revenue')
        headers = ['Rank', 'Campaign Name', 'Revenue', 'CTR', 'Sends', 'Clicks', 'Sessions', 'Purchases']
        data = []
        
        # Reverse for display (lowest first)
        bottom5_revenue_reversed = list(reversed(bottom5_by_revenue))
        for idx, campaign in enumerate(bottom5_revenue_reversed, 1):
            ga4 = campaign.get('ga4_metrics', {})
            campaign_name = campaign['name']
            if len(campaign_name) > 50:
                campaign_name = campaign_name[:47] + "..."
            
            data.append([
                idx,
                campaign_name,
                format_currency(ga4.get('revenue', 0)),
                format_pct(campaign.get('braze_click_rate', 0)),
                format_number(campaign.get('braze_sends', 0)),
                format_number(campaign.get('braze_clicks', 0)),
                format_number(ga4.get('sessions', 0)),
                ga4.get('purchases', 0),
            ])
        
        if data:
            pdf.add_table(headers, data, col_widths=[12, 85, 22, 15, 18, 15, 15, 15])
        else:
            pdf.body_text("No campaigns with revenue data.")
        pdf.ln(5)
        
        # Top 5 by CTR
        pdf.section_title(f'{brand} - Top 5 by CTR')
        headers = ['Rank', 'Campaign Name', 'CTR', 'Sends', 'Clicks', 'Revenue', 'Sessions', 'Purchases']
        data = []
        
        for idx, campaign in enumerate(top5_by_ctr, 1):
            ga4 = campaign.get('ga4_metrics', {})
            campaign_name = campaign['name']
            if len(campaign_name) > 50:
                campaign_name = campaign_name[:47] + "..."
            
            data.append([
                idx,
                campaign_name,
                format_pct(campaign.get('braze_click_rate', 0)),
                format_number(campaign.get('braze_sends', 0)),
                format_number(campaign.get('braze_clicks', 0)),
                format_currency(ga4.get('revenue', 0)),
                format_number(ga4.get('sessions', 0)),
                ga4.get('purchases', 0),
            ])
        
        if data:
            pdf.add_table(headers, data, col_widths=[12, 85, 15, 18, 15, 22, 15, 15])
        else:
            pdf.body_text("No campaigns with CTR data.")
        pdf.ln(5)
        
        # Bottom 5 by CTR
        pdf.section_title(f'{brand} - Bottom 5 by CTR')
        headers = ['Rank', 'Campaign Name', 'CTR', 'Sends', 'Clicks', 'Revenue', 'Sessions', 'Purchases']
        data = []
        
        # Reverse for display (lowest first)
        bottom5_ctr_reversed = list(reversed(bottom5_by_ctr))
        for idx, campaign in enumerate(bottom5_ctr_reversed, 1):
            ga4 = campaign.get('ga4_metrics', {})
            campaign_name = campaign['name']
            if len(campaign_name) > 50:
                campaign_name = campaign_name[:47] + "..."
            
            data.append([
                idx,
                campaign_name,
                format_pct(campaign.get('braze_click_rate', 0)),
                format_number(campaign.get('braze_sends', 0)),
                format_number(campaign.get('braze_clicks', 0)),
                format_currency(ga4.get('revenue', 0)),
                format_number(ga4.get('sessions', 0)),
                ga4.get('purchases', 0),
            ])
        
        if data:
            pdf.add_table(headers, data, col_widths=[12, 85, 15, 18, 15, 22, 15, 15])
        else:
            pdf.body_text("No campaigns with CTR data.")
    
    # Save PDF
    output_path = Path(__file__).parent.parent / "p-campaigns-performance-report.pdf"
    pdf.output(str(output_path))
    
    print(f"\nPDF written to {output_path}")
    print(f"\nSummary:")
    print(f"  Total P_ campaigns analyzed: {len(all_p_campaigns)}")
    for brand in sorted(campaigns_by_brand.keys()):
        print(f"    {brand}: {len(campaigns_by_brand[brand])} campaigns")


if __name__ == "__main__":
    generate_p_campaigns_report()


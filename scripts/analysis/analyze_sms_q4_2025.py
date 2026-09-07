#!/usr/bin/env python3
"""
SMS Performance Analysis: Q4 2025 (October 1 - December 31, 2025)

Combines Braze SMS campaign performance data with GA4 metrics from CSV files
to generate a comprehensive analysis report showing top 5 SMS per brand.

Usage:
    uv run python scripts/analyze_sms_q4_2025.py
"""

import os
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv
import requests

# Import Braze functions
sys.path.insert(0, str(Path(__file__).parent))
from import_braze import (
    normalize_brand,
    get_config,
    init_config,
    get_campaigns,
    get_campaign_details,
    get_campaign_analytics,
)

# PDF generation
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

# Brand mapping for CSV files
# Note: SF (St. Frank) uses STF in Braze API keys
BRAND_CSV_MAPPING = {
    "TI": "/Users/jordan.rubenstein/Downloads/TI SMS 20251001-20251231.csv",
    "SF": "/Users/jordan.rubenstein/Downloads/SF SMS 20251001-20251231.csv",
    "CZ": "/Users/jordan.rubenstein/Downloads/CZ SMS 20251001-20251231.csv",
    "BW": "/Users/jordan.rubenstein/Downloads/BW SMS 20251001-20251231.csv",
    "ID": "/Users/jordan.rubenstein/Downloads/ID SMS 20251001-20251231.csv",
}

# Brand mapping for Braze API (some brands use different codes)
BRAND_BRAZE_MAPPING = {
    "TI": "TI",
    "SF": "STF",  # St. Frank uses STF in Braze
    "CZ": "CZ",
    "BW": "BUR",  # Burrow uses BUR in Braze
    "ID": "ID",
}

# Date range for analysis
START_DATE = datetime(2025, 10, 1)
END_DATE = datetime(2025, 12, 31, 23, 59, 59)


def parse_ga4_csv(csv_path, brand):
    """Parse GA4 CSV file and extract campaign metrics.
    
    Returns dict mapping campaign name -> metrics dict with:
    - sessions: int
    - purchases: int (or transactions)
    - revenue: float
    """
    if not os.path.exists(csv_path):
        print(f"Warning: CSV file not found: {csv_path}")
        return {}
    
    campaigns = {}
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            # Skip comment lines at the beginning
            lines = f.readlines()
            header_line_idx = None
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith('#'):
                    header_line_idx = i
                    break
            
            if header_line_idx is None:
                print(f"Warning: No header found in {csv_path}")
                return {}
            
            # Parse from header line
            f.seek(0)
            for _ in range(header_line_idx):
                next(f)
            
            reader = csv.DictReader(f)
            
            for row in reader:
                # Skip grand total rows
                row_values_str = ' '.join(str(v) for v in row.values())
                if 'Grand total' in row_values_str or not row_values_str.strip():
                    continue
                
                # Get campaign name - different CSV files use different column names
                campaign_name = None
                
                # For SF CSV, it has "Session primary channel group" and "Session campaign" columns
                # We want the "Session campaign" column value when channel is SMS
                if brand == "SF" and "Session campaign" in row:
                    channel_group = row.get("Session primary channel group (Default Channel Group)", "").strip()
                    if channel_group == "SMS" and row["Session campaign"]:
                        campaign_name = row["Session campaign"].strip()
                else:
                    # For other brands, use "Session campaign" or "campaign" column
                    for col in ['Session campaign', 'campaign']:
                        if col in row and row[col] and row[col].strip():
                            campaign_name = row[col].strip()
                            break
                
                if not campaign_name or campaign_name == '':
                    continue
                
                # Exclude triggered/drip SMS campaigns (TRG_ prefix)
                if campaign_name.upper().startswith('TRG_'):
                    continue
                
                # Extract metrics based on available columns
                sessions = 0
                purchases = 0
                revenue = 0.0
                
                # Sessions
                for col in ['Sessions', 'sessions']:
                    if col in row and row[col]:
                        try:
                            sessions = int(float(row[col]))
                        except (ValueError, TypeError):
                            pass
                        break
                
                # Purchases/Transactions - different files use different column names
                # BW CSV uses "Ecommerce purchases"
                purchase_cols = ['Ecommerce purchases', 'Purchases', 'Transactions', 'purchases', 'transactions']
                for col in purchase_cols:
                    if col in row and row[col]:
                        try:
                            purchases = int(float(row[col]))
                        except (ValueError, TypeError):
                            pass
                        break
                
                # Revenue
                for col in ['Total revenue', 'totalRevenue', 'revenue']:
                    if col in row and row[col]:
                        try:
                            revenue = float(row[col])
                        except (ValueError, TypeError):
                            pass
                        break
                
                if campaign_name:
                    campaigns[campaign_name] = {
                        'sessions': sessions,
                        'purchases': purchases,
                        'revenue': revenue,
                    }
    
    except Exception as e:
        print(f"Error parsing CSV {csv_path}: {e}")
        import traceback
        traceback.print_exc()
        return {}
    
    return campaigns


def braze_request_brand(brand, endpoint, params=None):
    """Make a Braze API request for a specific brand."""
    # Map brand code to Braze brand code
    braze_brand = BRAND_BRAZE_MAPPING.get(brand, brand)
    config = get_config(braze_brand)
    if not config or not config.get("api_key"):
        return None
    
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    url = f"{config['base_url']}/{endpoint}"
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  Error {response.status_code} for {brand} {endpoint}: {response.text[:200]}")
    except Exception as e:
        print(f"  Error requesting {brand} {endpoint}: {e}")
    
    return None


def is_sms_campaign(campaign_name):
    """Check if campaign name indicates SMS channel.
    
    Handles various naming patterns:
    - P_SMS_2025_12_09_... (underscore format with SMS in middle, e.g., _SMS_)
    - SMS_2025_... (starts with SMS_)
    - ..._SMS (ends with _SMS, e.g., P_2025_10_09_The_Autumn_Event_SMS)
    - ..._SMS_... (SMS with underscores on both sides)
    - ... SMS (space before SMS)
    - ...-SMS-... (dash format, e.g., 20221216-EOY-Sale-SMS-AL)
    - ..._sms-... (lowercase sms with dash, e.g., P_2024_09_16_fall_collection_preview_sms-2024-09-16)
    """
    if not campaign_name:
        return False
    name_upper = campaign_name.upper()
    name_lower = campaign_name.lower()
    
    # Standard patterns (uppercase)
    # Check for _SMS_ (underscores on both sides) or _SMS (underscore before)
    # Using regex to match _SMS followed by end of string, underscore, dash, or space
    import re
    if (re.search(r'_SMS[_\-]|_SMS$', name_upper) or
            name_upper.startswith("SMS_") or 
            name_upper.endswith("_SMS") or
            " SMS" in name_upper or
            "-SMS-" in name_upper or
            name_upper.endswith("-SMS") or
            "_SMS_" in name_upper):
        return True
    
    # Lowercase patterns with dash (e.g., ..._sms-2024-...)
    if "_sms-" in name_lower or "-sms-" in name_lower:
        return True
    
    return False


def get_sms_campaigns_from_braze(brand, max_pages=20):
    """Fetch SMS campaigns from Braze (without strict date filtering).
    
    Returns list of campaign dicts with:
    - id: campaign ID
    - name: campaign name
    - created_at: creation date
    - tags: campaign tags
    """
    campaigns = []
    
    # Fetch campaign list
    params = {
        "page": 0,
        "include_archived": False,
        "sort_direction": "desc"
    }
    
    while params["page"] < max_pages:
        data = braze_request_brand(brand, "campaigns/list", params)
        if not data or "campaigns" not in data:
            break
        
        batch = data["campaigns"]
        if not batch:
            break
        
        for campaign in batch:
            campaign_name = campaign.get('name', '')
            
            # Exclude triggered/drip SMS campaigns (TRG_ prefix)
            if campaign_name.upper().startswith('TRG_'):
                continue
            
            # Filter to SMS campaigns only
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


def extract_sms_body_and_links(details):
    """Extract SMS body text and links from Braze campaign details.
    
    Returns tuple: (body_text, links_list)
    """
    body_text = None
    links = []
    
    if not details or "messages" not in details:
        return None, []
    
    for msg_key, msg_data in details.get("messages", {}).items():
        if isinstance(msg_data, dict):
            # Check if it's an SMS message
            msg_channel = msg_data.get("channel", "")
            msg_type = msg_data.get("type", "")
            
            if msg_channel == "sms" or "sms" in msg_type.lower():
                body = msg_data.get("body", "")
                if body and body.strip():
                    body_text = body.strip()
                    # Extract URLs from body text
                    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                    links = re.findall(url_pattern, body_text)
                    break
            
            # Also check for body without subject (SMS won't have subject)
            if not body_text and not msg_data.get("subject"):
                body = msg_data.get("body", "")
                if body and body.strip():
                    body_text = body.strip()
                    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                    links = re.findall(url_pattern, body_text)
                    break
    
    return body_text, links


def get_sms_creative_and_links(campaign_id, brand):
    """Fetch SMS creative (body text) and links from Braze.
    
    Returns tuple: (body_text, links_list)
    """
    details = braze_request_brand(brand, "campaigns/details", {"campaign_id": campaign_id})
    if not details:
        return None, []
    
    return extract_sms_body_and_links(details)


def normalize_campaign_name(name):
    """Normalize campaign name for matching."""
    if not name:
        return ""
    # Remove extra whitespace, convert to lowercase
    normalized = re.sub(r'\s+', ' ', name.strip().lower())
    return normalized


def extract_date_from_campaign_name(name):
    """Extract date from campaign name patterns like P_SMS_2025_12_15_... or 2025_12_15_...
    
    Returns datetime object or None.
    """
    if not name:
        return None
    # Pattern: YYYY_M(M)_D(D) - supports single or double digit month/day
    match = re.search(r'(\d{4})[-_](\d{1,2})[-_](\d{1,2})', name)
    if match:
        try:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return datetime(year, month, day)
        except (ValueError, TypeError):
            pass
    return None


def match_campaigns_to_ga4(ga4_data, braze_campaigns):
    """Match GA4 CSV data to Braze campaigns by campaign name.
    
    Returns list of matched campaigns with combined data.
    This approach uses CSV data as the source of truth.
    """
    matched = []
    
    # Create normalized lookup for Braze campaigns
    braze_lookup = {}
    for braze_campaign in braze_campaigns:
        campaign_name = braze_campaign.get('name', '')
        normalized = normalize_campaign_name(campaign_name)
        braze_lookup[normalized] = braze_campaign
    
    # Match from GA4 data (source of truth)
    for ga4_name, ga4_metrics in ga4_data.items():
        normalized_ga4 = normalize_campaign_name(ga4_name)
        
        # Try exact match first
        if normalized_ga4 in braze_lookup:
            braze_campaign = braze_lookup[normalized_ga4]
            matched.append({
                'braze_id': braze_campaign['id'],
                'name': ga4_name,  # Use GA4 name as primary
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
                # Check if one contains the other (for variations)
                if normalized_ga4 in braze_normalized or braze_normalized in normalized_ga4:
                    # Calculate similarity score
                    overlap = len(set(normalized_ga4.split()) & set(braze_normalized.split()))
                    total = len(set(normalized_ga4.split()) | set(braze_normalized.split()))
                    score = overlap / total if total > 0 else 0
                    
                    if score > best_score and score > 0.6:  # Require at least 60% similarity
                        best_score = score
                        best_match = braze_campaign
            
            if best_match:
                matched.append({
                    'braze_id': best_match['id'],
                    'name': ga4_name,  # Use GA4 name as primary
                    'braze_name': best_match.get('name', ''),
                    'ga4_name': ga4_name,
                    'ga4_metrics': ga4_metrics.copy(),
                    'created_at': best_match.get('created_at'),
                })
    
    return matched


def find_unmatched_braze_campaigns_with_high_sends(braze_campaigns, matched_braze_ids, brand, start_date, end_date, min_sends=1000):
    """Find Braze SMS campaigns with high sends that aren't in GA4 data.
    
    Args:
        braze_campaigns: List of all Braze SMS campaigns
        matched_braze_ids: Set of Braze campaign IDs that were matched to GA4
        brand: Brand code
        start_date: Start date for analytics
        end_date: End date for analytics
        min_sends: Minimum sends threshold (default 1000)
    
    Returns list of campaigns with sends >= min_sends that don't match GA4 data.
    """
    unmatched_high_sends = []
    
    print(f"  Checking {len(braze_campaigns)} Braze campaigns for unmatched high-send campaigns...")
    unmatched_campaigns = [c for c in braze_campaigns if c['id'] not in matched_braze_ids]
    print(f"    {len(unmatched_campaigns)} unmatched campaigns to check")
    
    for i, braze_campaign in enumerate(unmatched_campaigns):
        
        if (i + 1) % 20 == 0:
            print(f"    Progress: {i + 1}/{len(unmatched_campaigns)}")
        
        braze_id = braze_campaign['id']
        campaign_name = braze_campaign.get('name', '')
        
        # Fetch analytics
        try:
            analytics_data = braze_request_brand(
                brand,
                "campaigns/data_series",
                {
                    "campaign_id": braze_id,
                    "length": min((end_date - start_date).days + 1, 100),
                    "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S-05:00")
                }
            )
            
            if analytics_data and "data" in analytics_data:
                total_sends = 0
                total_clicks = 0
                total_delivered = 0
                
                for day_data in analytics_data.get("data", []):
                    messages = day_data.get("messages", {})
                    for channel, variants in messages.items():
                        if isinstance(variants, list):
                            for variant in variants:
                                total_sends += variant.get("sent", 0)
                                if channel == "sms":
                                    total_clicks += variant.get("clicks", 0)
                                else:
                                    total_clicks += variant.get("unique_clicks", 0)
                                total_delivered += variant.get("delivered", 0)
                
                if total_sends >= min_sends:
                    unmatched_high_sends.append({
                        'braze_id': braze_id,
                        'name': campaign_name,
                        'braze_sends': total_sends,
                        'braze_clicks': total_clicks,
                        'braze_delivered': total_delivered,
                        'braze_click_rate': total_clicks / total_sends if total_sends > 0 else 0,
                        'created_at': braze_campaign.get('created_at'),
                    })
        except Exception as e:
            # Skip errors silently for this check
            pass
    
    return unmatched_high_sends


def fetch_braze_analytics_for_campaigns(matched_campaigns, brand, start_date, end_date):
    """Fetch Braze analytics for matched campaigns.
    
    Updates matched_campaigns in-place with Braze performance data.
    """
    print(f"  Fetching Braze analytics for {len(matched_campaigns)} campaigns...")
    
    for i, campaign in enumerate(matched_campaigns):
        if (i + 1) % 10 == 0:
            print(f"    Progress: {i + 1}/{len(matched_campaigns)}")
        
        braze_id = campaign['braze_id']
        
        # Fetch analytics
        analytics = None
        try:
            # Get campaign details first to check send dates
            details = braze_request_brand(brand, "campaigns/details", {"campaign_id": braze_id})
            if details:
                # Try to get analytics
                analytics_data = braze_request_brand(
                    brand,
                    "campaigns/data_series",
                    {
                        "campaign_id": braze_id,
                        "length": min((end_date - start_date).days + 1, 100),
                        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S-05:00")
                    }
                )
                if analytics_data and "data" in analytics_data:
                    analytics = analytics_data
        except Exception as e:
            print(f"    Error fetching analytics for {campaign['name']}: {e}")
        
        # Parse analytics
        total_sends = 0
        total_clicks = 0
        total_delivered = 0
        
        if analytics:
            for day_data in analytics.get("data", []):
                messages = day_data.get("messages", {})
                for channel, variants in messages.items():
                    if isinstance(variants, list):
                        for variant in variants:
                            total_sends += variant.get("sent", 0)
                            # SMS uses "clicks" field, email uses "unique_clicks"
                            if channel == "sms":
                                total_clicks += variant.get("clicks", 0)
                            else:
                                total_clicks += variant.get("unique_clicks", 0)
                            total_delivered += variant.get("delivered", 0)
        
        campaign['braze_sends'] = total_sends
        campaign['braze_clicks'] = total_clicks
        campaign['braze_delivered'] = total_delivered
        campaign['braze_click_rate'] = total_clicks / total_sends if total_sends > 0 else 0
        
        # Fetch SMS creative
        body_text, links = get_sms_creative_and_links(braze_id, brand)
        campaign['sms_body'] = body_text
        campaign['sms_links'] = links


def infer_brand_from_campaign_name(name):
    """Infer brand from campaign name."""
    if not name:
        return None
    
    name_upper = name.upper()
    
    # Brand patterns - note SF (St. Frank) uses SF_ or STF_ patterns
    brand_patterns = {
        "TI": ["_TI_", "_TI-", "TI_", "TI-"],
        "SF": ["_SF_", "_SF-", "SF_", "SF-", "STF_", "ST_FRANK", "_STF_"],
        "CZ": ["_CZ_", "_CZ-", "CZ_", "CZ-"],
        "BW": ["_BW_", "_BW-", "BW_", "BW-", "BURROW", "BUR_"],
        "ID": ["_ID_", "_ID-", "ID_", "ID-", "INTERIOR_DEFINE"],
    }
    
    for brand, patterns in brand_patterns.items():
        if any(pattern in name_upper for pattern in patterns):
            return brand
    
    return None


def rank_campaigns_by_brand(all_campaigns):
    """Rank campaigns by brand and select top 5 per brand.
    
    Returns dict mapping brand -> list of top 5 campaigns.
    """
    # Group by brand
    by_brand = defaultdict(list)
    
    for campaign in all_campaigns:
        # Infer brand from campaign name
        brand = infer_brand_from_campaign_name(campaign.get('name', ''))
        
        if not brand:
            # Skip if we can't determine brand
            continue
        
        campaign['brand'] = brand
        by_brand[brand].append(campaign)
    
    # Rank and select top 5 per brand
    top_by_brand = {}
    
    for brand, campaigns in by_brand.items():
        # Filter to campaigns with meaningful data
        valid_campaigns = [
            c for c in campaigns
            if (c.get('ga4_metrics', {}).get('revenue', 0) > 0 or
                c.get('braze_clicks', 0) > 0 or
                c.get('ga4_metrics', {}).get('sessions', 0) > 0)
        ]
        
        # Sort by CTR (primary), then revenue (secondary), then sessions
        sorted_campaigns = sorted(
            valid_campaigns,
            key=lambda x: (
                -x.get('braze_click_rate', 0),
                -x.get('ga4_metrics', {}).get('revenue', 0),
                -x.get('ga4_metrics', {}).get('sessions', 0)
            )
        )
        
        top_by_brand[brand] = sorted_campaigns[:5]
    
    return top_by_brand


def format_pct(value, decimals=2):
    """Format a decimal as percentage."""
    return f"{value * 100:.{decimals}f}%"


def calculate_revenue_per_million_sends(revenue, sends):
    """Calculate revenue per million sends ($/M)."""
    if sends == 0:
        return 0.0
    return (revenue / sends) * 1_000_000


def format_currency_per_m(value):
    """Format revenue per million sends."""
    if value == 0:
        return "$0/M"
    rounded = round(value)
    return f"${rounded:,}/M"


def format_number(value):
    """Format large numbers with commas."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(int(value)) if value > 0 else "0"


def format_currency(value):
    """Format currency value rounded to nearest dollar."""
    if value == 0:
        return "$0"
    rounded = round(value)
    # Add comma separators for thousands
    return f"${rounded:,}"


def sanitize_text_for_pdf(text):
    """Remove or replace characters that can't be encoded in PDF fonts."""
    if not text:
        return text
    
    # Remove emojis and other non-ASCII characters that can't be encoded
    # Keep ASCII characters and common Unicode characters
    import unicodedata
    try:
        # Try to encode to ASCII with replacement
        text = text.encode('ascii', 'ignore').decode('ascii')
    except Exception:
        # Fall back to removing problematic characters
        text = ''.join(c for c in text if ord(c) < 128 or unicodedata.category(c)[0] != 'So')
    
    return text


class PDFReport(FPDF):
    """Custom PDF class for SMS Q4 2025 analysis."""
    
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
        
    def bullet_point(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(51)
        x = self.get_x()
        self.cell(8, 5, chr(149), new_x=XPos.RIGHT)
        self.multi_cell(0, 5, text)
        self.set_x(x)
    
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


def generate_pdf_report(all_campaigns, top_by_brand, output_path):
    """Generate PDF report from analysis data.
    
    Args:
        all_campaigns: List of all matched campaigns with data
        top_by_brand: Dict mapping brand -> list of top 5 campaigns
        output_path: Path to save PDF
    """
    pdf = PDFReport()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'SMS Performance Analysis: Q4 2025', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, 'October 1 - December 31, 2025 | All SMS Campaigns', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Aggregate all campaigns by brand
    all_by_brand = defaultdict(list)
    for campaign in all_campaigns:
        brand = campaign.get('brand')
        if brand:
            all_by_brand[brand].append(campaign)
    
    # Executive Summary - ALL campaigns
    pdf.chapter_title('Executive Summary - All SMS Campaigns')
    
    total_campaigns = len(all_campaigns)
    total_revenue = 0
    total_sessions = 0
    total_purchases = 0
    total_sends = 0
    total_clicks = 0
    
    for campaign in all_campaigns:
        total_revenue += campaign.get('ga4_metrics', {}).get('revenue', 0)
        total_sessions += campaign.get('ga4_metrics', {}).get('sessions', 0)
        total_purchases += campaign.get('ga4_metrics', {}).get('purchases', 0)
        total_sends += campaign.get('braze_sends', 0)
        total_clicks += campaign.get('braze_clicks', 0)
    
    overall_ctr = (total_clicks / total_sends * 100) if total_sends > 0 else 0.0
    
    pdf.section_title('Overall Metrics')
    pdf.bullet_point(f"Total SMS campaigns: {total_campaigns} across {len(all_by_brand)} brands")
    pdf.bullet_point(f"Total revenue: {format_currency(total_revenue)}")
    pdf.bullet_point(f"Total sessions: {format_number(total_sessions)}")
    pdf.bullet_point(f"Total purchases: {total_purchases}")
    pdf.bullet_point(f"Total sends: {format_number(total_sends)}")
    pdf.bullet_point(f"Total clicks: {format_number(total_clicks)}")
    pdf.bullet_point(f"Overall CTR: {format_pct(overall_ctr / 100, decimals=2)}")
    pdf.ln(5)
    
    # Brand Performance Overview - ALL campaigns
    pdf.add_page()
    pdf.chapter_title('Brand Performance Overview - All SMS Campaigns')
    
    pdf.body_text('Summary of all SMS campaigns per brand:')
    pdf.ln(2)
    
    # Summary table for ALL campaigns
    headers = ['Brand', 'Campaigns', 'Revenue', 'Sessions', 'Purchases', 'Sends', 'Clicks', 'CTR', '$/M']
    data = []
    
    for brand in sorted(all_by_brand.keys()):
        campaigns = all_by_brand[brand]
        brand_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in campaigns)
        brand_sessions = sum(c.get('ga4_metrics', {}).get('sessions', 0) for c in campaigns)
        brand_purchases = sum(c.get('ga4_metrics', {}).get('purchases', 0) for c in campaigns)
        brand_sends = sum(c.get('braze_sends', 0) for c in campaigns)
        brand_clicks = sum(c.get('braze_clicks', 0) for c in campaigns)
        brand_ctr = (brand_clicks / brand_sends * 100) if brand_sends > 0 else 0.0
        revenue_per_m = calculate_revenue_per_million_sends(brand_revenue, brand_sends)
        
        data.append([
            brand,
            str(len(campaigns)),
            format_currency(brand_revenue),
            format_number(brand_sessions),
            str(brand_purchases),
            format_number(brand_sends) if brand_sends > 0 else "0",
            format_number(brand_clicks) if brand_clicks > 0 else "0",
            format_pct(brand_ctr / 100, decimals=2),
            format_currency_per_m(revenue_per_m),
        ])
    
    # Add table
    pdf.add_table(headers, data, col_widths=[18, 18, 25, 20, 20, 22, 22, 20, 20])
    
    # Top 5 Summary
    pdf.add_page()
    pdf.chapter_title('Top 5 SMS Campaigns by Brand')
    
    pdf.body_text('Summary of top 5 SMS campaigns per brand:')
    pdf.ln(2)
    
    # Summary table for TOP 5
    headers = ['Brand', 'Campaigns', 'Revenue', 'Sessions', 'Purchases', 'Avg CTR', 'Total Clicks', '$/M']
    data = []
    
    for brand in sorted(top_by_brand.keys()):
        campaigns = top_by_brand[brand]
        brand_revenue = sum(c.get('ga4_metrics', {}).get('revenue', 0) for c in campaigns)
        brand_sessions = sum(c.get('ga4_metrics', {}).get('sessions', 0) for c in campaigns)
        brand_purchases = sum(c.get('ga4_metrics', {}).get('purchases', 0) for c in campaigns)
        
        # Calculate Braze metrics
        total_clicks = sum(c.get('braze_clicks', 0) for c in campaigns)
        total_sends = sum(c.get('braze_sends', 0) for c in campaigns)
        avg_ctr = (total_clicks / total_sends * 100) if total_sends > 0 else 0.0
        
        # Calculate average CTR (mean of individual CTRs)
        ctrs = [c.get('braze_click_rate', 0) for c in campaigns if c.get('braze_sends', 0) > 0]
        avg_ctr_mean = (sum(ctrs) / len(ctrs) * 100) if ctrs else 0.0
        
        revenue_per_m = calculate_revenue_per_million_sends(brand_revenue, total_sends)
        
        data.append([
            brand,
            str(len(campaigns)),
            format_currency(brand_revenue),
            format_number(brand_sessions),
            str(brand_purchases),
            format_pct(avg_ctr_mean / 100, decimals=2),
            format_number(total_clicks) if total_clicks > 0 else "0",
            format_currency_per_m(revenue_per_m),
        ])
    
    # Add table
    pdf.add_table(headers, data, col_widths=[18, 22, 28, 22, 22, 22, 22, 20])
    
    # Top 5 SMS by Brand
    for brand in sorted(top_by_brand.keys()):
        campaigns = top_by_brand[brand]
        if not campaigns:
            continue
        
        pdf.add_page()
        pdf.chapter_title(f'{brand} - Top 5 SMS Campaigns')
        
        for idx, campaign in enumerate(campaigns, 1):
            pdf.section_title(f'{idx}. {campaign["name"]}')
            
            # Metrics
            ga4 = campaign.get('ga4_metrics', {})
            pdf.body_text(f"Revenue: {format_currency(ga4.get('revenue', 0))}")
            pdf.body_text(f"Sessions: {format_number(ga4.get('sessions', 0))}")
            pdf.body_text(f"Purchases: {ga4.get('purchases', 0)}")
            
            if campaign.get('braze_sends', 0) > 0:
                pdf.body_text(f"Sends: {format_number(campaign.get('braze_sends', 0))}")
                pdf.body_text(f"Clicks: {format_number(campaign.get('braze_clicks', 0))}")
                pdf.body_text(f"CTR: {format_pct(campaign.get('braze_click_rate', 0))}")
            
            # SMS copy (includes links, so no separate Links section)
            sms_body = campaign.get('sms_body')
            if sms_body:
                pdf.ln(2)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(52, 73, 94)
                pdf.cell(0, 6, 'SMS Copy:', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(51)
                # Truncate long messages and sanitize for PDF
                display_body = sms_body[:300] + "..." if len(sms_body) > 300 else sms_body
                display_body = sanitize_text_for_pdf(display_body)
                pdf.multi_cell(0, 5, display_body)
            
            pdf.ln(5)
    
    # Save PDF
    pdf.output(str(output_path))
    print(f"\nPDF written to {output_path}")


def filter_campaigns_with_extractable_dates(campaigns, start_date, end_date):
    """Filter campaigns to only include those with extractable dates in the date range.
    
    Returns filtered list of campaigns that have dates in their names within the date range.
    """
    filtered = []
    
    for campaign in campaigns:
        campaign_name = campaign.get('name', '')
        campaign_date = extract_date_from_campaign_name(campaign_name)
        
        # Include if date is extractable and within range
        if campaign_date and start_date <= campaign_date <= end_date:
            filtered.append(campaign)
    
    return filtered


def clean_campaign_name(name):
    """Simplify campaign name for slide deck readability."""
    if not name:
        return ""
    # Remove date prefix patterns like P_SMS_2025_10_06_ or P_2025_10_06_
    name = re.sub(r'^P_SMS_\d{4}_\d{1,2}_\d{1,2}_', '', name)
    name = re.sub(r'^P_\d{4}_\d{1,2}_\d{1,2}_', '', name)
    name = re.sub(r'^\d{8}_', '', name)  # Remove patterns like 20251006_
    # Replace underscores with spaces
    name = name.replace('_', ' ')
    return name.strip()


def export_top5_for_slides(all_campaigns, top_by_brand):
    """Export top 5 campaigns per brand to CSV in slide-deck friendly format."""
    output_path = Path(__file__).parent.parent / "top5-sms-campaigns-slides.csv"
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Key metrics for slides
        writer.writerow(['Brand', 'Rank', 'Campaign Name', 'Revenue', 'CTR', 'Sends', 'Clicks'])
        
        for brand in sorted(top_by_brand.keys()):
            campaigns = top_by_brand[brand]
            for idx, campaign in enumerate(campaigns, 1):
                ga4 = campaign.get('ga4_metrics', {})
                clean_name = clean_campaign_name(campaign['name'])
                writer.writerow([
                    brand,
                    idx,
                    clean_name,
                    format_currency(ga4.get('revenue', 0)),
                    format_pct(campaign.get('braze_click_rate', 0)),
                    f"{campaign.get('braze_sends', 0):,}",
                    f"{campaign.get('braze_clicks', 0):,}",
                ])
    
    print(f"  Exported top 5 campaigns to {output_path}")
    
    # Print summary
    print("  Summary:")
    for brand in sorted(top_by_brand.keys()):
        campaigns = top_by_brand[brand]
        print(f"    {brand}: {len(campaigns)} campaigns")


def export_december_sms_campaigns(all_campaigns):
    """Export a chronological list of December SMS campaigns by brand to CSV."""
    # Filter to December 2025 campaigns
    december_campaigns = []
    
    for campaign in all_campaigns:
        campaign_name = campaign.get('name', '')
        campaign_date = extract_date_from_campaign_name(campaign_name)
        
        # Check if it's December 2025 (or use created_at as fallback)
        if campaign_date and campaign_date.year == 2025 and campaign_date.month == 12:
            brand = infer_brand_from_campaign_name(campaign_name)
            if brand and brand != "TI":  # Skip TI
                december_campaigns.append({
                    'brand': brand,
                    'date': campaign_date,
                    'name': campaign_name,
                    'revenue': campaign.get('ga4_metrics', {}).get('revenue', 0),
                    'sessions': campaign.get('ga4_metrics', {}).get('sessions', 0),
                    'purchases': campaign.get('ga4_metrics', {}).get('purchases', 0),
                    'sends': campaign.get('braze_sends', 0),
                    'clicks': campaign.get('braze_clicks', 0),
                    'ctr': campaign.get('braze_click_rate', 0),
                })
        elif not campaign_date:
            # Try to use created_at as fallback
            created_at = campaign.get('created_at')
            if created_at:
                try:
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        created_dt = created_at
                    if created_dt.year == 2025 and created_dt.month == 12:
                        brand = infer_brand_from_campaign_name(campaign_name)
                        if brand and brand != "TI":
                            december_campaigns.append({
                                'brand': brand,
                                'date': created_dt,
                                'name': campaign_name,
                                'revenue': campaign.get('ga4_metrics', {}).get('revenue', 0),
                                'sessions': campaign.get('ga4_metrics', {}).get('sessions', 0),
                                'purchases': campaign.get('ga4_metrics', {}).get('purchases', 0),
                                'sends': campaign.get('braze_sends', 0),
                                'clicks': campaign.get('braze_clicks', 0),
                                'ctr': campaign.get('braze_click_rate', 0),
                            })
                except Exception:
                    pass
    
    # Sort by brand, then by date
    december_campaigns.sort(key=lambda x: (x['brand'], x['date']))
    
    # Export to CSV
    output_path = Path(__file__).parent.parent / "december-2025-sms-campaigns.csv"
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Brand', 'Date', 'Campaign Name', 'Revenue', 'Sessions', 'Purchases', 'Sends', 'Clicks', 'CTR'])
        
        for camp in december_campaigns:
            writer.writerow([
                camp['brand'],
                camp['date'].strftime('%Y-%m-%d'),
                camp['name'],
                f"${int(round(camp['revenue'])):,}" if camp['revenue'] > 0 else "$0",
                camp['sessions'],
                camp['purchases'],
                camp['sends'],
                camp['clicks'],
                f"{camp['ctr'] * 100:.2f}%" if camp['ctr'] > 0 else "0%",
            ])
    
    # Print summary by brand
    by_brand = defaultdict(list)
    for camp in december_campaigns:
        by_brand[camp['brand']].append(camp)
    
    print(f"  Exported {len(december_campaigns)} December SMS campaigns to {output_path}")
    print("  Summary by brand:")
    for brand in sorted(by_brand.keys()):
        campaigns = by_brand[brand]
        print(f"    {brand}: {len(campaigns)} campaigns")


def main():
    """Main function to run the analysis."""
    print("SMS Performance Analysis: Q4 2025")
    print("=" * 60)
    
    # Parse GA4 CSV files
    print("\n1. Parsing GA4 CSV files...")
    all_ga4_data = {}
    for brand, csv_path in BRAND_CSV_MAPPING.items():
        print(f"  Parsing {brand} CSV...")
        ga4_data = parse_ga4_csv(csv_path, brand)
        all_ga4_data[brand] = ga4_data
        print(f"    Found {len(ga4_data)} campaigns")
    
    # Fetch SMS campaigns from Braze (for matching)
    print("\n2. Fetching SMS campaigns from Braze for matching...")
    all_braze_campaigns = {}
    for brand in BRAND_CSV_MAPPING.keys():
        print(f"  Fetching {brand} campaigns...")
        campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
        all_braze_campaigns[brand] = campaigns
        print(f"    Found {len(campaigns)} SMS campaigns")
    
    # Match campaigns and fetch analytics
    print("\n3. Matching campaigns and fetching analytics...")
    all_matched = []
    
    for brand in BRAND_CSV_MAPPING.keys():
        print(f"\n  Processing {brand}...")
        braze_campaigns = all_braze_campaigns[brand]
        ga4_data = all_ga4_data[brand]
        
        # Match campaigns (CSV-driven: match CSV campaigns to Braze)
        matched = match_campaigns_to_ga4(ga4_data, braze_campaigns)
        print(f"    Matched {len(matched)} campaigns (from {len(ga4_data)} CSV campaigns)")
        
        # Fetch Braze analytics and creative
        fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
        
        all_matched.extend(matched)
    
    print(f"\n  Total matched campaigns: {len(all_matched)}")
    
    # Filter to only campaigns with extractable dates (Oct-Dec 2025)
    print("\n3b. Filtering campaigns with extractable dates...")
    all_matched = filter_campaigns_with_extractable_dates(all_matched, START_DATE, END_DATE)
    print(f"  Filtered to {len(all_matched)} campaigns with extractable dates in Oct-Dec 2025")
    
    # Check for unmatched Braze campaigns with high sends
    print("\n3a. Checking for unmatched Braze SMS campaigns with 1k+ sends...")
    all_unmatched_high_sends = []
    
    # Collect matched Braze IDs by brand
    matched_braze_ids_by_brand = {}
    for brand in BRAND_CSV_MAPPING.keys():
        if brand == "TI":  # Skip TI as requested
            continue
        matched_for_brand = [m for m in all_matched if infer_brand_from_campaign_name(m.get('name', '')) == brand]
        matched_braze_ids_by_brand[brand] = {m['braze_id'] for m in matched_for_brand}
    
    for brand in BRAND_CSV_MAPPING.keys():
        if brand == "TI":  # Skip TI as requested
            continue
        print(f"\n  Checking {brand}...")
        braze_campaigns = all_braze_campaigns[brand]
        matched_braze_ids = matched_braze_ids_by_brand.get(brand, set())
        unmatched = find_unmatched_braze_campaigns_with_high_sends(
            braze_campaigns, matched_braze_ids, brand, START_DATE, END_DATE, min_sends=1000
        )
        all_unmatched_high_sends.extend(unmatched)
        print(f"    Found {len(unmatched)} unmatched campaigns with 1k+ sends")
        if unmatched:
            print("    Unmatched campaigns:")
            for camp in sorted(unmatched, key=lambda x: -x.get('braze_sends', 0))[:10]:  # Show top 10
                print(f"      - {camp['name']}: {camp.get('braze_sends', 0):,} sends, "
                      f"{camp.get('braze_clicks', 0):,} clicks, "
                      f"CTR: {format_pct(camp.get('braze_click_rate', 0))}")
    
    if all_unmatched_high_sends:
        print(f"\n  Total unmatched campaigns with 1k+ sends: {len(all_unmatched_high_sends)}")
    else:
        print("\n  No unmatched campaigns with 1k+ sends found.")
    
    # Rank campaigns by brand
    print("\n4. Ranking campaigns by brand...")
    top_by_brand = rank_campaigns_by_brand(all_matched)
    
    for brand, campaigns in sorted(top_by_brand.items()):
        print(f"  {brand}: {len(campaigns)} top campaigns")
    
    # Generate PDF report
    print("\n5. Generating PDF report...")
    output_path = Path(__file__).parent.parent / "sms-q4-2025-analysis.pdf"
    generate_pdf_report(all_matched, top_by_brand, output_path)
    
    # Export December SMS campaigns chronologically
    print("\n6. Exporting December SMS campaigns...")
    export_december_sms_campaigns(all_matched)
    
    # Export top 5 campaigns for slide deck
    print("\n7. Exporting top 5 campaigns for slide deck...")
    export_top5_for_slides(all_matched, top_by_brand)
    
    print("\nDone!")


if __name__ == "__main__":
    main()


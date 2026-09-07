#!/usr/bin/env python3
"""
SMS CTR Focused Analysis

Analyzes the top 5 and worst 5 SMS campaigns by click-through rate,
including the actual message copy in the report.

Outputs: sms-ctr-focused-analysis.pdf
"""

import os
import yaml
import re
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from dotenv import load_dotenv
import requests

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

# Load .env for Braze API access
load_dotenv(Path(__file__).parent.parent / ".env")


def load_campaigns():
    """Load all SMS campaign YAML files."""
    campaigns = []
    
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if data and data.get("channel") == "sms":
                    data["_filename"] = yaml_file.name
                    campaigns.append(data)
        except Exception as e:
            print(f"Error loading {yaml_file.name}: {e}")
    
    return campaigns


def filter_valid_sms_campaigns(campaigns):
    """Filter to SMS campaigns with valid performance data."""
    valid = []
    for c in campaigns:
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0)
        click_rate = perf.get("click_rate", 0)
        # Include campaigns with at least 1000 sends and a valid click rate
        if sends >= 1000 and click_rate >= 0:
            valid.append(c)
    return valid


def get_campaign_details_from_braze(braze_id, brand=None):
    """Fetch campaign details from Braze API."""
    # Get API key for brand
    if brand:
        api_key = os.environ.get(f"BRAZE_API_KEY_{brand}")
        base_url = os.environ.get(f"BRAZE_BASE_URL_{brand}", "https://rest.iad-07.braze.com")
    else:
        api_key = os.environ.get("BRAZE_API_KEY")
        base_url = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
    
    if not api_key:
        return None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{base_url}/campaigns/details"
    params = {"campaign_id": braze_id}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching from Braze for {braze_id}: {e}")
    
    return None


def get_sms_copy(campaign):
    """Extract SMS message copy from campaign."""
    # Try to get body text from sends in YAML
    body_text = None
    if campaign.get("sends"):
        for send in campaign["sends"]:
            body = send.get("body", "")
            if body and body.strip():
                body_text = body.strip()
                break  # Take first send variant with body text
    
    # If not in YAML, try fetching from Braze API
    if not body_text:
        braze_id = campaign.get("braze_id")
        brand = campaign.get("brand")
        if braze_id:
            details = get_campaign_details_from_braze(braze_id, brand)
            if details and "messages" in details:
                for msg_key, msg_data in details.get("messages", {}).items():
                    if isinstance(msg_data, dict):
                        # Check if it's an SMS message
                        msg_channel = msg_data.get("channel", "")
                        msg_type = msg_data.get("type", "")
                        if msg_channel == "sms" or "sms" in msg_type.lower():
                            body = msg_data.get("body", "")
                            if body and body.strip():
                                body_text = body.strip()
                                break
                        # Also check for body in SMS messages
                        if not body_text:
                            body = msg_data.get("body", "")
                            if body and body.strip() and not msg_data.get("subject"):  # SMS won't have subject
                                body_text = body.strip()
                                break
    
    return body_text


def get_top_and_worst_campaigns_by_brand(campaigns, top_n=5, worst_n=5, min_days_old=3):
    """Get top N and worst N campaigns by CTR for each brand.
    
    Args:
        campaigns: List of campaign dicts
        top_n: Number of top campaigns per brand
        worst_n: Number of worst campaigns per brand
        min_days_old: Minimum days since last_sent to include (excludes very recent campaigns)
    """
    from collections import defaultdict
    from datetime import datetime, timedelta
    
    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=min_days_old)
    
    # Group campaigns by brand
    brand_campaigns = defaultdict(list)
    excluded_recent = []
    
    # First pass: collect all valid campaigns without fetching SMS copy (to avoid unnecessary API calls)
    for c in campaigns:
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0)
        clicks = perf.get("total_clicks", 0)
        click_rate = perf.get("click_rate", 0)
        
        if sends >= 1000:  # Minimum threshold
            # Check if campaign is too recent
            dates = c.get("dates", {})
            last_sent_str = dates.get("last_sent")
            is_too_recent = False
            
            if last_sent_str:
                try:
                    # Parse the date (handle both ISO format and simple date format)
                    if 'T' in last_sent_str:
                        last_sent = datetime.fromisoformat(last_sent_str.replace('Z', '+00:00'))
                    else:
                        last_sent = datetime.strptime(last_sent_str, "%Y-%m-%d")
                    
                    # Remove timezone info for comparison
                    if last_sent.tzinfo:
                        last_sent = last_sent.replace(tzinfo=None)
                    
                    if last_sent > cutoff_date:
                        is_too_recent = True
                        excluded_recent.append({
                            "name": c.get("name", "Unknown"),
                            "brand": c.get("brand", "Unknown"),
                            "last_sent": last_sent_str,
                            "sends": sends,
                            "click_rate": click_rate
                        })
                except (ValueError, AttributeError):
                    # If we can't parse the date, include it (better to include than exclude)
                    pass
            
            # Skip campaigns that are too recent
            if is_too_recent:
                continue
            
            brand = c.get("brand", "Unknown")
            # Try to get SMS copy from YAML first (fast, no API call)
            sms_copy = None
            if c.get("sends"):
                for send in c["sends"]:
                    body = send.get("body", "")
                    if body and body.strip():
                        sms_copy = body.strip()
                        break
            
            brand_campaigns[brand].append({
                "name": c.get("name", "Unknown"),
                "brand": brand,
                "category": c.get("category", "other"),
                "sends": sends,
                "clicks": clicks,
                "click_rate": click_rate,
                "sms_copy": sms_copy,  # May be None if not in YAML
                "campaign": c
            })
    
    # Report excluded campaigns
    if excluded_recent:
        print(f"\nExcluded {len(excluded_recent)} campaigns sent within the last {min_days_old} days (may have incomplete data):")
        for exc in excluded_recent[:10]:  # Show first 10
            print(f"  - {exc['brand']}: {exc['name']} (sent {exc['last_sent']}, {exc['sends']} sends, {format_pct(exc['click_rate'])} CTR)")
        if len(excluded_recent) > 10:
            print(f"  ... and {len(excluded_recent) - 10} more")
    
    # Get top and worst for each brand
    results_by_brand = {}
    
    for brand, brand_list in brand_campaigns.items():
        # Sort by click rate
        sorted_campaigns = sorted(brand_list, key=lambda x: -x["click_rate"])
        
        # Get top N
        top_campaigns = sorted_campaigns[:top_n]
        
        # For worst, filter out campaigns with 0 clicks (they might be incomplete data)
        campaigns_with_clicks = [c for c in sorted_campaigns if c["clicks"] > 0]
        worst_campaigns = sorted(campaigns_with_clicks, key=lambda x: x["click_rate"])[:worst_n]
        
        results_by_brand[brand] = {
            "top": top_campaigns,
            "worst": worst_campaigns
        }
    
    # Now fetch SMS copy from Braze API for campaigns that don't have it yet
    # (only for top/worst to minimize API calls)
    print("Fetching SMS copy from Braze API for top/worst campaigns by brand...")
    for brand, results in results_by_brand.items():
        for campaign_data in results["top"] + results["worst"]:
            if not campaign_data["sms_copy"]:
                sms_copy = get_sms_copy(campaign_data["campaign"])
                if sms_copy:
                    campaign_data["sms_copy"] = sms_copy
                    print(f"  Found SMS copy for: {brand} - {campaign_data['name']}")
    
    return results_by_brand


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


def analyze_language_patterns(results_by_brand):
    """Analyze language patterns from top 5 vs worst 5 campaigns per brand."""
    all_top_texts = []
    all_worst_texts = []
    
    # Collect SMS copy from top and worst performers
    for brand, results in results_by_brand.items():
        for campaign in results["top"]:
            sms_copy = campaign.get("sms_copy")
            if sms_copy:
                all_top_texts.append(sms_copy.lower())
        
        for campaign in results["worst"]:
            sms_copy = campaign.get("sms_copy")
            if sms_copy:
                all_worst_texts.append(sms_copy.lower())
    
    if not all_top_texts and not all_worst_texts:
        return None
    
    # Extract words (excluding URLs and common stopwords)
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'get', 'got', 'go', 'goes', 'went', 'come', 'came', 'see', 'saw', 'know', 'knew',
        'http', 'https', 'www', 'com', 'org', 'net', 'co', 'io', 'link', 'click', 'here'
    }
    
    def extract_words(text):
        """Extract meaningful words from SMS text."""
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'www\.\S+', '', text)
        # Remove special characters but keep spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        # Split into words
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        # Filter stopwords and short words
        return [w for w in words if w not in stopwords and len(w) >= 3]
    
    # Extract words only
    top_words = []
    for text in all_top_texts:
        top_words.extend(extract_words(text))
    
    worst_words = []
    for text in all_worst_texts:
        worst_words.extend(extract_words(text))
    
    # Count frequencies
    top_word_freq = Counter(top_words)
    worst_word_freq = Counter(worst_words)
    
    # Calculate relative frequencies
    num_top = len(all_top_texts)
    num_worst = len(all_worst_texts)
    
    # Word comparison
    all_words = set(top_word_freq.keys()) | set(worst_word_freq.keys())
    word_comparison = []
    
    for word in all_words:
        top_count = top_word_freq.get(word, 0)
        worst_count = worst_word_freq.get(word, 0)
        top_pct = top_count / num_top if num_top > 0 else 0
        worst_pct = worst_count / num_worst if num_worst > 0 else 0
        
        # Only include words that appear in at least 10% of campaigns
        if top_pct >= 0.1 or worst_pct >= 0.1:
            word_comparison.append({
                "word": word,
                "top_freq": top_pct,
                "worst_freq": worst_pct,
                "difference": top_pct - worst_pct
            })
    
    word_comparison.sort(key=lambda x: -x["difference"])
    
    # Words to use (appear more in top performers)
    words_to_use = [w for w in word_comparison if w["difference"] > 0.05][:20]
    
    # Words to avoid (appear more in worst performers)
    words_to_avoid = [w for w in word_comparison if w["difference"] < -0.05][:20]
    words_to_avoid.reverse()  # Show worst first
    
    return {
        "top_count": num_top,
        "worst_count": num_worst,
        "words_to_use": words_to_use,
        "words_to_avoid": words_to_avoid
    }


def clean_text_for_pdf(text):
    """Remove or replace Unicode characters that can't be encoded in PDF."""
    if not text:
        return text
    
    # Try to encode as latin-1, replacing problematic characters
    try:
        # First try to encode - if it works, return as-is
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        # Replace problematic characters
        # Remove emojis and other non-latin-1 characters
        cleaned = ""
        for char in text:
            try:
                char.encode('latin-1')
                cleaned += char
            except UnicodeEncodeError:
                # Replace with a placeholder or skip
                # Common emoji replacements
                if char in ['🌈', '✨', '🎉', '🔥', '💯', '⭐', '🌟']:
                    cleaned += "*"
                elif char in ['💰', '💵', '💸']:
                    cleaned += "$"
                elif char in ['📧', '📱', '💬']:
                    cleaned += ""
                elif char in ['❤️', '💙', '💚', '💛', '🧡', '💜']:
                    cleaned += "<3"
                elif char in ['→', '←', '↑', '↓']:
                    cleaned += "->" if char == '→' else char
                # For other Unicode, just skip
                pass
        return cleaned


class PDFReport(FPDF):
    """Custom PDF class for focused SMS CTR analysis."""
    
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
        self.set_font('Helvetica', 'B', 18)
        self.set_text_color(44, 62, 80)
        self.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)
        
    def section_title(self, title):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(52, 73, 94)
        self.cell(0, 9, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        
    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(51)
        self.multi_cell(0, 5, text)
        self.ln(2)
        
    def sms_copy_box(self, text):
        """Display SMS copy in a styled box."""
        # Clean text to remove problematic Unicode characters
        cleaned_text = clean_text_for_pdf(text)
        
        self.set_font('Helvetica', '', 9)
        self.set_text_color(51)
        self.set_fill_color(245, 247, 250)
        self.set_draw_color(200, 200, 200)
        
        # Calculate height needed with proper text wrapping
        text_width = 180  # Account for padding (5px on each side)
        lines = self._split_text(cleaned_text, text_width)
        box_height = len(lines) * 4.5 + 6  # Slightly tighter line spacing
        
        # Check if we're too close to bottom of page
        if self.get_y() + box_height > 280:  # Leave some margin
            self.add_page()
        
        # Draw box
        x = self.get_x()
        y = self.get_y()
        self.rect(x, y, 190, box_height, style='FD')
        
        # Add text with padding, using the pre-split lines
        self.set_x(x + 5)
        self.set_y(y + 3)
        # Render each line individually to ensure proper wrapping
        for line in lines:
            # Ensure line fits within width
            if self.get_string_width(line) > 180:
                # If still too wide, use multi_cell for this line
                self.multi_cell(180, 4.5, line)
            else:
                self.cell(180, 4.5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(x)
        self.set_y(y + box_height + 3)
        
    def _split_text(self, text, max_width):
        """Split text into lines that fit within max_width, handling URLs properly."""
        # Clean text first to avoid encoding issues
        cleaned_text = clean_text_for_pdf(text)
        
        words = cleaned_text.split(' ')
        lines = []
        current_line = []
        current_width = 0
        
        for word in words:
            try:
                word_width = self.get_string_width(word + ' ')
                
                # If a single word (like a URL) is too long, break it
                if word_width > max_width:
                    # Break long words/URLs at safe characters
                    if '/' in word or 'http' in word.lower() or '.' in word:
                        # It's likely a URL, break at / or .
                        parts = []
                        current_part = ""
                        for char in word:
                            test_part = current_part + char
                            test_width = self.get_string_width(test_part)
                            if test_width > max_width and current_part:
                                parts.append(current_part)
                                current_part = char
                            else:
                                current_part = test_part
                        if current_part:
                            parts.append(current_part)
                        
                        # Add parts to lines
                        for i, part in enumerate(parts):
                            if current_line:
                                lines.append(' '.join(current_line))
                                current_line = []
                                current_width = 0
                            lines.append(part)
                        continue
                    else:
                        # Very long word, just truncate
                        word = word[:50] + "..."
                        word_width = self.get_string_width(word + ' ')
                
                if current_width + word_width <= max_width:
                    current_line.append(word)
                    current_width += word_width
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
                    current_width = word_width
            except:
                # If there's still an encoding issue, skip this word
                continue
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines if lines else [cleaned_text]
        
    def campaign_detail(self, campaign_data, rank, compact=False):
        """Display detailed campaign information."""
        # Rank and basic info - more compact
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(44, 62, 80)
        # Truncate long campaign names
        name = campaign_data['name']
        if len(name) > 60:
            name = name[:57] + "..."
        self.cell(0, 6, f"#{rank} - {name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Brand, category, and metrics on one line
        self.set_font('Helvetica', '', 8)
        self.set_text_color(100)
        category = campaign_data['category'].replace('_', ' ').title()
        metrics = f"{campaign_data['brand']} | {category} | CTR: {format_pct(campaign_data['click_rate'])} | {format_number(campaign_data['sends'])} sends"
        self.cell(0, 4, metrics, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        
        # SMS Copy
        self.set_font('Helvetica', 'B', 8)
        self.set_text_color(52, 73, 94)
        self.cell(0, 5, "SMS Copy:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        
        sms_copy = campaign_data.get('sms_copy')
        if sms_copy:
            self.sms_copy_box(sms_copy)
        else:
            # If no body text, show campaign name formatted nicely
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(120)
            self.sms_copy_box(f"[Message copy not available]")
        
        self.ln(3)


def generate_pdf(campaigns, output_path):
    """Generate focused PDF report from SMS campaign data."""
    pdf = PDFReport()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'SMS CTR Focused Analysis', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, 'Top 5 and Worst 5 Campaigns by Brand', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Get top and worst campaigns by brand
    results_by_brand = get_top_and_worst_campaigns_by_brand(campaigns, top_n=5, worst_n=5)
    
    # Calculate date range
    first_dates = []
    last_dates = []
    for c in campaigns:
        dates = c.get("dates", {})
        if dates.get("first_sent"):
            first_dates.append(dates["first_sent"])
        if dates.get("last_sent"):
            last_dates.append(dates["last_sent"])
    
    date_range_text = ""
    if first_dates and last_dates:
        earliest = min(first_dates)
        latest = max(last_dates)
        # Format dates nicely
        try:
            from datetime import datetime
            earliest_dt = datetime.fromisoformat(earliest.replace('Z', '+00:00'))
            latest_dt = datetime.fromisoformat(latest.replace('Z', '+00:00'))
            date_range_text = f"Date Range: {earliest_dt.strftime('%B %d, %Y')} - {latest_dt.strftime('%B %d, %Y')}"
        except:
            date_range_text = f"Date Range: {earliest[:10]} - {latest[:10]}"
    
    # Executive Summary
    pdf.chapter_title('Executive Summary')
    
    # Count how many campaigns were actually analyzed (after exclusions)
    total_analyzed = sum(len(results["top"]) + len(results["worst"]) for results in results_by_brand.values())
    
    pdf.body_text(f"This report analyzes SMS campaigns with 1,000+ sends, showing the top 5 and worst 5 performers by click-through rate for each brand.")
    pdf.body_text(f"Note: Campaigns sent within the last 3 days are excluded to avoid artificially low CTRs from incomplete data.")
    if date_range_text:
        pdf.body_text(date_range_text)
    pdf.ln(3)
    
    # Summary stats by brand
    all_best = []
    all_worst = []
    for brand, results in results_by_brand.items():
        if results["top"]:
            all_best.append(results["top"][0])
        if results["worst"]:
            all_worst.append(results["worst"][0])
    
    if all_best:
        best_overall = max(all_best, key=lambda x: x['click_rate'])
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(51)
        pdf.cell(0, 6, f"Best Performing Campaign Overall:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 6, f"  {best_overall['name']} ({best_overall['brand']}) - {format_pct(best_overall['click_rate'])} CTR", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
    
    if all_worst:
        worst_overall = min(all_worst, key=lambda x: x['click_rate'])
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(51)
        pdf.cell(0, 6, f"Worst Performing Campaign Overall:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 6, f"  {worst_overall['name']} ({worst_overall['brand']}) - {format_pct(worst_overall['click_rate'])} CTR", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(5)
    
    # Campaigns by Brand (Top 5 then Worst 5 for each brand)
    for brand in sorted(results_by_brand.keys()):
        brand_results = results_by_brand[brand]
        top_campaigns = brand_results["top"]
        worst_campaigns = brand_results["worst"]
        
        # Top 5 for this brand
        if top_campaigns:
            pdf.add_page()
            pdf.chapter_title(f'{brand} - Top 5 Performing Campaigns')
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(51)
            pdf.cell(0, 5, f'Top 5 SMS campaigns for {brand} by click-through rate.', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)
            
            for i, campaign in enumerate(top_campaigns, 1):
                # Check if we need a new page (leave room for at least one more campaign)
                if pdf.get_y() > 250:  # Too close to bottom
                    pdf.add_page()
                pdf.campaign_detail(campaign, i, compact=True)
        
        # Worst 5 for this brand
        if worst_campaigns:
            pdf.add_page()
            pdf.chapter_title(f'{brand} - Worst 5 Performing Campaigns')
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(51)
            pdf.cell(0, 5, f'Worst 5 SMS campaigns for {brand} by click-through rate.', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)
            
            for i, campaign in enumerate(worst_campaigns, 1):
                # Check if we need a new page (leave room for at least one more campaign)
                if pdf.get_y() > 250:  # Too close to bottom
                    pdf.add_page()
                pdf.campaign_detail(campaign, i, compact=True)
    
    # Language Analysis
    language_analysis = analyze_language_patterns(results_by_brand)
    
    if language_analysis:
        pdf.add_page()
        pdf.chapter_title('Language Pattern Analysis')
        pdf.body_text(f"Analyzed SMS copy from {language_analysis['top_count']} top-performing campaigns vs {language_analysis['worst_count']} worst-performing campaigns to identify what messaging works.")
        pdf.ln(5)
        
        if language_analysis.get('words_to_use'):
            pdf.section_title('Words Associated with High Performance')
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(51)
            pdf.body_text('These words appear more frequently in top-performing SMS campaigns:')
            pdf.ln(2)
            for word_data in language_analysis['words_to_use'][:15]:
                top_pct = word_data['top_freq'] * 100
                worst_pct = word_data['worst_freq'] * 100
                pdf.set_font('Helvetica', 'B', 9)
                pdf.cell(30, 5, word_data['word'].title(), new_x=XPos.RIGHT)
                pdf.set_font('Helvetica', '', 8)
                pdf.set_text_color(100)
                pdf.cell(0, 5, f"in {top_pct:.0f}% of top vs {worst_pct:.0f}% of worst", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(51)
            pdf.ln(3)
        
        if language_analysis.get('words_to_avoid'):
            pdf.section_title('Words to Use Sparingly')
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(51)
            pdf.body_text('These words appear more frequently in worst-performing SMS campaigns:')
            pdf.ln(2)
            for word_data in language_analysis['words_to_avoid'][:15]:
                top_pct = word_data['top_freq'] * 100
                worst_pct = word_data['worst_freq'] * 100
                pdf.set_font('Helvetica', 'B', 9)
                pdf.cell(30, 5, word_data['word'].title(), new_x=XPos.RIGHT)
                pdf.set_font('Helvetica', '', 8)
                pdf.set_text_color(100)
                pdf.cell(0, 5, f"in {worst_pct:.0f}% of worst vs {top_pct:.0f}% of top", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(51)
            pdf.ln(5)
    
    # Key Insights
    pdf.add_page()
    pdf.chapter_title('Key Insights & Recommendations')
    
    pdf.section_title('Brand Performance Summary')
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(51)
    
    # Calculate averages by brand
    for brand in sorted(results_by_brand.keys()):
        brand_results = results_by_brand[brand]
        top_campaigns = brand_results["top"]
        worst_campaigns = brand_results["worst"]
        
        if top_campaigns:
            avg_top_ctr = sum(c['click_rate'] for c in top_campaigns) / len(top_campaigns)
            pdf.body_text(f"- {brand}: Top 5 average CTR: {format_pct(avg_top_ctr)}")
        
        if worst_campaigns:
            avg_worst_ctr = sum(c['click_rate'] for c in worst_campaigns) / len(worst_campaigns)
            pdf.body_text(f"  Worst 5 average CTR: {format_pct(avg_worst_ctr)}")
            
            if top_campaigns:
                improvement = (avg_top_ctr - avg_worst_ctr) / avg_worst_ctr if avg_worst_ctr > 0 else 0
                pdf.body_text(f"  Improvement potential: {format_pct(improvement)} if worst reach top levels")
    
    pdf.ln(5)
    pdf.section_title('What Makes Top Performers Successful?')
    
    # Collect all top campaigns across brands
    all_top = []
    all_worst = []
    for brand, results in results_by_brand.items():
        all_top.extend(results["top"])
        all_worst.extend(results["worst"])
    
    if all_top:
        top_categories = [c['category'] for c in all_top]
        category_counts = {}
        for cat in top_categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if category_counts:
            most_common_cat = max(category_counts.items(), key=lambda x: x[1])
            pdf.body_text(f"- '{most_common_cat[0].replace('_', ' ').title()}' category appears {most_common_cat[1]} times across top 5 lists - this campaign type resonates")
        
        # Check if we have SMS copy for top performers
        top_with_copy = [c for c in all_top if c.get('sms_copy')]
        if top_with_copy:
            pdf.body_text(f"- {len(top_with_copy)} of {len(all_top)} top campaigns have message copy available - review the messaging patterns")
    
    pdf.ln(5)
    pdf.section_title('What Can We Learn from Underperformers?')
    if all_worst:
        worst_categories = [c['category'] for c in all_worst]
        category_counts = {}
        for cat in worst_categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if category_counts:
            most_common_cat = max(category_counts.items(), key=lambda x: x[1])
            pdf.body_text(f"- '{most_common_cat[0].replace('_', ' ').title()}' category appears {most_common_cat[1]} times across worst 5 lists - this campaign type may need messaging refinement")
    
    pdf.ln(5)
    pdf.section_title('Action Items')
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(51)
    pdf.body_text("1. Review the SMS copy from top performers and identify common messaging patterns")
    pdf.body_text("2. Compare top vs worst performer messaging to understand what resonates")
    if language_analysis and language_analysis.get('words_to_use'):
        top_words = ", ".join([w['word'].title() for w in language_analysis['words_to_use'][:5]])
        pdf.body_text(f"3. Incorporate words associated with high performance: {top_words}")
    else:
        pdf.body_text("3. Test messaging elements from top performers in future campaigns")
    if language_analysis and language_analysis.get('words_to_avoid'):
        avoid_words = ", ".join([w['word'].title() for w in language_analysis['words_to_avoid'][:5]])
        pdf.body_text(f"4. Avoid overusing words associated with low performance: {avoid_words}")
    else:
        pdf.body_text("4. For underperforming campaigns, consider A/B testing new messaging approaches")
    pdf.body_text("5. Monitor brand and category patterns - some may need specialized strategies")
    pdf.body_text("6. Use the language pattern analysis above to guide future SMS copywriting")
    
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128)
    pdf.cell(0, 5, f"Analysis generated {datetime.now().strftime('%B %d, %Y')}", align='C')
    
    # Save PDF
    pdf.output(str(output_path))
    print(f"PDF written to {output_path}")


def main():
    print("Loading SMS campaigns...")
    campaigns = load_campaigns()
    print(f"Loaded {len(campaigns)} SMS campaign files")
    
    valid_campaigns = filter_valid_sms_campaigns(campaigns)
    print(f"Found {len(valid_campaigns)} SMS campaigns with 1000+ sends")
    
    # Generate PDF
    pdf_path = Path(__file__).parent.parent / "sms-ctr-focused-analysis.pdf"
    print("\nGenerating focused PDF report...")
    generate_pdf(valid_campaigns, pdf_path)
    
    print("\nDone!")


if __name__ == "__main__":
    main()


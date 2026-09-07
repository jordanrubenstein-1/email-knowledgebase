#!/usr/bin/env python3
"""
SMS Performance Analysis

Analyzes SMS campaign performance across brands to identify:
- What's working well
- What's not working
- Language patterns (words/phrases to use or avoid)
- Campaign type performance
- Brand-specific insights

Outputs: sms-performance-analysis.md and sms-performance-analysis.pdf
"""

import os
import yaml
import re
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


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
        if perf.get("total_sends", 0) >= 1000:  # Minimum threshold
            valid.append(c)
    return valid


def analyze_by_brand(campaigns):
    """Aggregate SMS metrics by brand."""
    brand_stats = defaultdict(lambda: {
        "campaigns": 0,
        "total_sends": 0,
        "total_clicks": 0,
        "total_opens": 0,
        "total_unsubs": 0,
        "campaign_list": []
    })
    
    for c in campaigns:
        brand = c.get("brand", "Unknown")
        perf = c.get("performance_summary", {})
        
        brand_stats[brand]["campaigns"] += 1
        brand_stats[brand]["total_sends"] += perf.get("total_sends", 0)
        brand_stats[brand]["total_clicks"] += perf.get("total_clicks", 0)
        brand_stats[brand]["total_opens"] += perf.get("total_opens", 0)
        brand_stats[brand]["total_unsubs"] += perf.get("total_unsubscribes", 0)
        brand_stats[brand]["campaign_list"].append(c)
    
    # Calculate rates and sort by click rate
    results = []
    for brand, stats in brand_stats.items():
        if stats["total_sends"] > 0:
            results.append({
                "brand": brand,
                "campaigns": stats["campaigns"],
                "sends": stats["total_sends"],
                "clicks": stats["total_clicks"],
                "opens": stats["total_opens"],
                "unsubs": stats["total_unsubs"],
                "click_rate": stats["total_clicks"] / stats["total_sends"],
                "open_rate": stats["total_opens"] / stats["total_sends"],
                "unsub_rate": stats["total_unsubs"] / stats["total_sends"],
                "campaign_list": stats["campaign_list"]
            })
    
    return sorted(results, key=lambda x: -x["click_rate"])


def analyze_by_category(campaigns):
    """Analyze SMS performance by campaign category."""
    category_stats = defaultdict(lambda: {
        "campaigns": 0,
        "sends": 0,
        "clicks": 0
    })
    
    for c in campaigns:
        category = c.get("category", "other")
        perf = c.get("performance_summary", {})
        
        category_stats[category]["campaigns"] += 1
        category_stats[category]["sends"] += perf.get("total_sends", 0)
        category_stats[category]["clicks"] += perf.get("total_clicks", 0)
    
    results = []
    for cat, stats in category_stats.items():
        if stats["sends"] > 0:
            results.append({
                "category": cat,
                "campaigns": stats["campaigns"],
                "sends": stats["sends"],
                "clicks": stats["clicks"],
                "click_rate": stats["clicks"] / stats["sends"]
            })
    
    return sorted(results, key=lambda x: -x["click_rate"])


def extract_text_from_campaigns(campaigns):
    """Extract message text from SMS campaigns."""
    texts = []
    for c in campaigns:
        # Try to get body text from sends
        body_text = None
        if c.get("sends"):
            for send in c["sends"]:
                body = send.get("body", "")
                if body:
                    body_text = body
                    break  # Just take first send variant
        
        # Use body text if available, otherwise use campaign name
        # Campaign names often contain key messaging elements
        text_source = body_text if body_text else c.get("name", "")
        if text_source:
            texts.append({
                "text": text_source,
                "brand": c.get("brand"),
                "campaign": c.get("name"),
                "click_rate": c.get("performance_summary", {}).get("click_rate", 0),
                "sends": c.get("performance_summary", {}).get("total_sends", 0)
            })
    return texts


def analyze_language_patterns(campaigns):
    """Analyze language patterns in high vs low performing SMS campaigns."""
    # Split campaigns into high and low performers
    # Use median as threshold for more balanced analysis
    click_rates = [c.get("performance_summary", {}).get("click_rate", 0) for c in campaigns if c.get("performance_summary", {}).get("total_sends", 0) >= 1000]
    if not click_rates:
        return {
            "high_performers_count": 0,
            "low_performers_count": 0,
            "words_to_use": [],
            "words_to_avoid": [],
            "phrases_to_use": [],
            "phrases_to_avoid": []
        }
    
    median_ctr = sorted(click_rates)[len(click_rates) // 2]
    high_threshold = max(median_ctr * 1.5, 0.02)  # Top 50% or >2%
    low_threshold = min(median_ctr * 0.7, 0.015)  # Bottom 50% or <1.5%
    
    high_performers = [c for c in campaigns if c.get("performance_summary", {}).get("click_rate", 0) >= high_threshold]
    low_performers = [c for c in campaigns if c.get("performance_summary", {}).get("click_rate", 0) <= low_threshold and c.get("performance_summary", {}).get("click_rate", 0) > 0]
    
    texts_high = extract_text_from_campaigns(high_performers)
    texts_low = extract_text_from_campaigns(low_performers)
    
    # Extract words and phrases from campaign names/text
    # For campaign names, split on underscores and common separators
    high_words = []
    high_phrases = []
    for text_data in texts_high:
        text = text_data["text"].lower()
        # Split on various separators
        parts = re.split(r'[_\s-]+', text)
        words = [w for w in parts if len(w) >= 3 and not w.isdigit()]
        high_words.extend(words)
        
        # Also look for common phrases (2-3 word combinations)
        if '_' in text_data["text"]:
            phrases = [p.lower() for p in text_data["text"].split('_') if len(p) > 3]
            high_phrases.extend(phrases)
    
    low_words = []
    low_phrases = []
    for text_data in texts_low:
        text = text_data["text"].lower()
        parts = re.split(r'[_\s-]+', text)
        words = [w for w in parts if len(w) >= 3 and not w.isdigit()]
        low_words.extend(words)
        
        if '_' in text_data["text"]:
            phrases = [p.lower() for p in text_data["text"].split('_') if len(p) > 3]
            low_phrases.extend(phrases)
    
    # Count frequencies
    high_word_freq = Counter(high_words)
    low_word_freq = Counter(low_words)
    high_phrase_freq = Counter(high_phrases)
    low_phrase_freq = Counter(low_phrases)
    
    # Common stopwords to filter
    stopwords = {'sms', 'p_sms', 'p_', 'the', 'and', 'for', 'with', 'from', '2024', '2025'}
    
    # Word comparison
    all_words = set(high_word_freq.keys()) | set(low_word_freq.keys())
    word_comparison = []
    
    for word in all_words:
        if word in stopwords or len(word) < 3:
            continue
        high_count = high_word_freq.get(word, 0)
        low_count = low_word_freq.get(word, 0)
        high_pct = high_count / len(texts_high) if texts_high else 0
        low_pct = low_count / len(texts_low) if texts_low else 0
        
        # Lower threshold since we have fewer data points
        if high_pct > 0.05 or low_pct > 0.05:
            word_comparison.append({
                "word": word,
                "high_freq": high_pct,
                "low_freq": low_pct,
                "difference": high_pct - low_pct
            })
    
    word_comparison.sort(key=lambda x: -x["difference"])
    
    # Phrase comparison
    all_phrases = set(high_phrase_freq.keys()) | set(low_phrase_freq.keys())
    phrase_comparison = []
    
    for phrase in all_phrases:
        if any(sw in phrase for sw in stopwords) or len(phrase) < 4:
            continue
        high_count = high_phrase_freq.get(phrase, 0)
        low_count = low_phrase_freq.get(phrase, 0)
        high_pct = high_count / len(texts_high) if texts_high else 0
        low_pct = low_count / len(texts_low) if texts_low else 0
        
        if high_pct > 0.03 or low_pct > 0.03:
            phrase_comparison.append({
                "phrase": phrase,
                "high_freq": high_pct,
                "low_freq": low_pct,
                "difference": high_pct - low_pct
            })
    
    phrase_comparison.sort(key=lambda x: -x["difference"])
    
    # Words/phrases to use (appear more in high performers)
    words_to_use = [w for w in word_comparison if w["difference"] > 0.03][:15]
    phrases_to_use = [p for p in phrase_comparison if p["difference"] > 0.02][:10]
    
    # Words/phrases to avoid (appear more in low performers)
    words_to_avoid = [w for w in word_comparison if w["difference"] < -0.03][:15]
    phrases_to_avoid = [p for p in phrase_comparison if p["difference"] < -0.02][:10]
    words_to_avoid.reverse()
    phrases_to_avoid.reverse()
    
    return {
        "high_performers_count": len(high_performers),
        "low_performers_count": len(low_performers),
        "words_to_use": words_to_use,
        "words_to_avoid": words_to_avoid,
        "phrases_to_use": phrases_to_use,
        "phrases_to_avoid": phrases_to_avoid
    }


def identify_top_performers_by_brand(campaigns, top_n=5):
    """Identify top performing SMS campaigns per brand."""
    brand_campaigns = defaultdict(list)
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0)
        click_rate = perf.get("click_rate", 0)
        if sends >= 1000:  # Minimum sends threshold
            brand_campaigns[c.get("brand", "Unknown")].append({
                "name": c.get("name"),
                "brand": c.get("brand"),
                "sends": sends,
                "clicks": perf.get("total_clicks", 0),
                "click_rate": click_rate,
                "category": c.get("category", "other")
            })
    
    # Get top performers per brand
    top_by_brand = {}
    for brand, brand_list in brand_campaigns.items():
        sorted_campaigns = sorted(brand_list, key=lambda x: -x["click_rate"])
        top_by_brand[brand] = sorted_campaigns[:top_n]
    
    return top_by_brand


def identify_underperformers_by_brand(campaigns, bottom_n=5):
    """Identify underperforming SMS campaigns per brand."""
    brand_campaigns = defaultdict(list)
    
    for c in campaigns:
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0)
        click_rate = perf.get("click_rate", 0)
        if sends >= 1000 and click_rate > 0:  # Has some clicks but low rate
            brand_campaigns[c.get("brand", "Unknown")].append({
                "name": c.get("name"),
                "brand": c.get("brand"),
                "sends": sends,
                "clicks": perf.get("total_clicks", 0),
                "click_rate": click_rate,
                "category": c.get("category", "other")
            })
    
    # Get bottom performers per brand
    bottom_by_brand = {}
    for brand, brand_list in brand_campaigns.items():
        sorted_campaigns = sorted(brand_list, key=lambda x: x["click_rate"])
        bottom_by_brand[brand] = sorted_campaigns[:bottom_n]
    
    return bottom_by_brand


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


class PDFReport(FPDF):
    """Custom PDF class for SMS performance analysis."""
    
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


def generate_pdf(campaigns, output_path):
    """Generate PDF report from SMS campaign data."""
    pdf = PDFReport()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'SMS Performance Analysis', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(85)
    pdf.cell(0, 8, f'{len(campaigns):,} SMS campaigns analyzed across multiple brands', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Analyze data
    brand_stats = analyze_by_brand(campaigns)
    category_stats = analyze_by_category(campaigns)
    top_performers_by_brand = identify_top_performers_by_brand(campaigns, top_n=5)
    underperformers_by_brand = identify_underperformers_by_brand(campaigns, bottom_n=5)
    language_analysis = analyze_language_patterns(campaigns)
    
    # For overall top performers (for summary), get the absolute best across all brands
    all_campaigns_with_rate = []
    for c in campaigns:
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0)
        click_rate = perf.get("click_rate", 0)
        if sends >= 1000:
            all_campaigns_with_rate.append({
                "name": c.get("name"),
                "brand": c.get("brand"),
                "sends": sends,
                "clicks": perf.get("total_clicks", 0),
                "click_rate": click_rate
            })
    top_performers_overall = sorted(all_campaigns_with_rate, key=lambda x: -x["click_rate"])[:1]  # Just for summary
    
    # Executive Summary
    pdf.chapter_title('Executive Summary')
    
    if brand_stats:
        best_brand = brand_stats[0]
        pdf.section_title('Key Findings')
        pdf.bullet_point(f"Best performing brand: {best_brand['brand']} with {format_pct(best_brand['click_rate'])} click rate")
        pdf.bullet_point(f"Total SMS sends analyzed: {sum(b['sends'] for b in brand_stats):,}")
        pdf.bullet_point(f"Average click rate: {format_pct(sum(b['clicks'] for b in brand_stats) / sum(b['sends'] for b in brand_stats))}")
        if top_performers_overall:
            pdf.bullet_point(f"Highest single campaign: {format_pct(top_performers_overall[0]['click_rate'])} CTR ({top_performers_overall[0]['brand']} - {top_performers_overall[0]['name'][:40]})")
        pdf.bullet_point("Note: Top/underperforming campaigns are analyzed within each brand to ensure fair comparisons")
    
    pdf.ln(5)
    
    # Brand Performance
    pdf.chapter_title('Performance by Brand')
    pdf.body_text('SMS click-through rates by brand:')
    pdf.ln(2)
    
    headers = ['Brand', 'Campaigns', 'Total Sends', 'Click Rate', 'Clicks']
    data = []
    for b in brand_stats:
        data.append([
            b['brand'],
            f"{b['campaigns']:,}",
            format_number(b['sends']),
            format_pct(b['click_rate']),
            f"{b['clicks']:,}"
        ])
    
    pdf.add_table(headers, data, col_widths=[25, 30, 35, 30, 30])
    
    # Campaign Category Performance
    if category_stats:
        pdf.add_page()
        pdf.chapter_title('Performance by Campaign Category')
        pdf.body_text('Click rates by campaign type/category:')
        pdf.ln(2)
        
        headers = ['Category', 'Campaigns', 'Sends', 'Click Rate']
        data = []
        for cat in category_stats:
            data.append([
                cat['category'].replace('_', ' ').title(),
                f"{cat['campaigns']:,}",
                format_number(cat['sends']),
                format_pct(cat['click_rate'])
            ])
        
        pdf.add_table(headers, data, col_widths=[50, 30, 40, 30])
    
    # Top Performers by Brand
    if top_performers_by_brand:
        pdf.add_page()
        pdf.chapter_title('Top Performing Campaigns by Brand')
        pdf.body_text('Top 5 SMS campaigns per brand (compared within each brand for fair analysis):')
        pdf.ln(3)
        
        for brand in sorted(top_performers_by_brand.keys()):
            brand_top = top_performers_by_brand[brand]
            if not brand_top:
                continue
                
            pdf.section_title(f'{brand} - Top Performers')
            pdf.ln(1)
            
            headers = ['Campaign', 'Sends', 'Clicks', 'CTR']
            data = []
            for tp in brand_top:
                data.append([
                    tp['name'][:45],
                    format_number(tp['sends']),
                    f"{tp['clicks']:,}",
                    format_pct(tp['click_rate'])
                ])
            
            pdf.add_table(headers, data, col_widths=[80, 25, 25, 20])
            pdf.ln(2)
    
    # Underperformers by Brand
    if underperformers_by_brand:
        pdf.add_page()
        pdf.chapter_title('Underperforming Campaigns by Brand')
        pdf.body_text('Bottom 5 SMS campaigns per brand (compared within each brand for fair analysis - opportunities for improvement):')
        pdf.ln(3)
        
        for brand in sorted(underperformers_by_brand.keys()):
            brand_bottom = underperformers_by_brand[brand]
            if not brand_bottom:
                continue
                
            pdf.section_title(f'{brand} - Underperformers')
            pdf.ln(1)
            
            headers = ['Campaign', 'Sends', 'Clicks', 'CTR']
            data = []
            for up in brand_bottom:
                data.append([
                    up['name'][:45],
                    format_number(up['sends']),
                    f"{up['clicks']:,}",
                    format_pct(up['click_rate'])
                ])
            
            pdf.add_table(headers, data, col_widths=[80, 25, 25, 20])
            pdf.ln(2)
    
    # Language Analysis
    if language_analysis and (language_analysis.get('words_to_use') or language_analysis.get('words_to_avoid')):
        pdf.add_page()
        pdf.chapter_title('Language Pattern Analysis')
        pdf.body_text(f"Analyzed {language_analysis['high_performers_count']} high-performing campaigns vs {language_analysis['low_performers_count']} low-performing campaigns:")
        pdf.ln(3)
        
        if language_analysis.get('words_to_use'):
            pdf.section_title('Words Associated with High Performance')
            pdf.body_text('These words appear more frequently in high-performing SMS campaigns:')
            pdf.ln(1)
            for word_data in language_analysis['words_to_use'][:12]:
                pdf.bullet_point(f"{word_data['word'].title()} (appears in {word_data['high_freq']*100:.0f}% of high performers vs {word_data['low_freq']*100:.0f}% of low performers)")
            pdf.ln(3)
        
        if language_analysis.get('phrases_to_use'):
            pdf.section_title('Phrases Associated with High Performance')
            pdf.body_text('These phrases appear more frequently in high-performing SMS campaigns:')
            pdf.ln(1)
            for phrase_data in language_analysis['phrases_to_use'][:8]:
                pdf.bullet_point(f"{phrase_data['phrase'].title().replace('_', ' ')} (appears in {phrase_data['high_freq']*100:.0f}% of high performers)")
            pdf.ln(3)
        
        if language_analysis.get('words_to_avoid'):
            pdf.section_title('Words Associated with Low Performance')
            pdf.body_text('These words appear more frequently in low-performing SMS campaigns:')
            pdf.ln(1)
            for word_data in language_analysis['words_to_avoid'][:12]:
                pdf.bullet_point(f"{word_data['word'].title()} (appears in {word_data['low_freq']*100:.0f}% of low performers vs {word_data['high_freq']*100:.0f}% of high performers)")
        
        if language_analysis.get('phrases_to_avoid'):
            pdf.section_title('Phrases to Use Sparingly')
            pdf.body_text('These phrases appear more frequently in low-performing SMS campaigns:')
            pdf.ln(1)
            for phrase_data in language_analysis['phrases_to_avoid'][:8]:
                pdf.bullet_point(f"{phrase_data['phrase'].title().replace('_', ' ')} (appears in {phrase_data['low_freq']*100:.0f}% of low performers)")
    
    # Recommendations
    pdf.add_page()
    pdf.chapter_title('Recommendations')
    
    pdf.section_title('What\'s Working Well')
    if brand_stats:
        best_brand = brand_stats[0]
        pdf.bullet_point(f"{best_brand['brand']} has the highest SMS click rate at {format_pct(best_brand['click_rate'])} - study their approach")
    
    if category_stats:
        best_category = category_stats[0]
        pdf.bullet_point(f"{best_category['category'].replace('_', ' ').title()} campaigns perform best ({format_pct(best_category['click_rate'])} CTR)")
    
    if top_performers_by_brand:
        # Get the best campaign from each brand's top performers
        best_from_each_brand = []
        for brand, brand_top in top_performers_by_brand.items():
            if brand_top:
                best_from_each_brand.append(brand_top[0])
        if best_from_each_brand:
            avg_top_ctr = sum(c['click_rate'] for c in best_from_each_brand) / len(best_from_each_brand)
            pdf.bullet_point(f"Top campaigns within each brand average {format_pct(avg_top_ctr)} CTR - analyze their messaging and timing")
    
    pdf.ln(3)
    pdf.section_title('What\'s Not Working')
    if underperformers_by_brand:
        # Get average of worst campaigns per brand
        worst_from_each_brand = []
        for brand, brand_bottom in underperformers_by_brand.items():
            if brand_bottom:
                worst_from_each_brand.append(brand_bottom[0])
        if worst_from_each_brand:
            avg_bottom_ctr = sum(c['click_rate'] for c in worst_from_each_brand) / len(worst_from_each_brand)
            pdf.bullet_point(f"Underperforming campaigns within each brand average {format_pct(avg_bottom_ctr)} CTR - significant opportunity for improvement")
    
    if brand_stats and len(brand_stats) > 1:
        worst_brand = brand_stats[-1]
        pdf.bullet_point(f"{worst_brand['brand']} has the lowest SMS click rate ({format_pct(worst_brand['click_rate'])}) - needs strategy review")
    
    pdf.ln(3)
    pdf.section_title('Recommended Adjustments')
    pdf.bullet_point("Compare top vs bottom performers within each brand to identify what works for that brand's audience")
    pdf.bullet_point("Test messaging patterns from top-performing campaigns within each brand's context")
    if language_analysis and language_analysis.get('words_to_use'):
        top_words = ", ".join([w['word'].title() for w in language_analysis['words_to_use'][:5]])
        pdf.bullet_point(f"Incorporate words associated with high performance: {top_words}")
    if language_analysis and language_analysis.get('words_to_avoid'):
        avoid_words = ", ".join([w['word'].title() for w in language_analysis['words_to_avoid'][:5]])
        pdf.bullet_point(f"Avoid overusing words associated with low performance: {avoid_words}")
    pdf.bullet_point("Review and replicate strategies from each brand's top performing campaigns")
    pdf.bullet_point("A/B test different messaging approaches, especially for underperforming campaign types within each brand")
    
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128)
    pdf.cell(0, 5, f"Analysis generated {datetime.now().strftime('%B %Y')}", align='C')
    
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
    pdf_path = Path(__file__).parent.parent / "sms-performance-analysis.pdf"
    print("\nGenerating PDF report...")
    generate_pdf(valid_campaigns, pdf_path)
    
    print("\nDone!")


if __name__ == "__main__":
    main()


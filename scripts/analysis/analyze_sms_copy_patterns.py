#!/usr/bin/env python3
"""Analyze SMS copy patterns in top-performing campaigns by brand."""

import sys
import re
from pathlib import Path
from collections import Counter, defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from analyze_sms_q4_2025 import (
    parse_ga4_csv,
    get_sms_campaigns_from_braze,
    match_campaigns_to_ga4,
    fetch_braze_analytics_for_campaigns,
    filter_campaigns_with_extractable_dates,
    infer_brand_from_campaign_name,
    extract_sms_body_and_links,
    braze_request_brand,
    BRAND_CSV_MAPPING,
    START_DATE,
    END_DATE,
)

load_dotenv(Path(__file__).parent.parent / ".env")


def fetch_sms_copy_for_campaigns(campaigns, brand):
    """Fetch SMS body text for campaigns from Braze."""
    print(f"  Fetching SMS copy for {len(campaigns)} campaigns...")
    
    campaigns_with_copy = []
    
    for i, campaign in enumerate(campaigns):
        braze_id = campaign.get('braze_id')
        if not braze_id:
            continue
        
        try:
            # Get campaign details
            details = braze_request_brand(brand, f"campaigns/details", {
                "campaign_id": braze_id
            })
            
            if details:
                body_text, links = extract_sms_body_and_links(details)
                campaign['sms_body'] = body_text or ""
                campaign['sms_links'] = links or []
                campaigns_with_copy.append(campaign)
        
        except Exception as e:
            # Skip if details fetch fails
            pass
        
        if (i + 1) % 10 == 0:
            print(f"    Progress: {i + 1}/{len(campaigns)}")
    
    return campaigns_with_copy


def clean_text(text):
    """Clean and normalize text for analysis."""
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    # Remove common URL patterns
    text = re.sub(r'www\.[^\s]+', '', text)
    # Remove special characters but keep spaces and basic punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    return text


def extract_words(text):
    """Extract words from text, excluding common stop words."""
    stop_words = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
        'to', 'was', 'will', 'with', 'the', 'this', 'but', 'they', 'have',
        'had', 'what', 'said', 'each', 'which', 'their', 'time', 'if',
        'up', 'out', 'many', 'then', 'them', 'these', 'so', 'some', 'her',
        'would', 'make', 'like', 'into', 'him', 'has', 'two', 'more',
        'very', 'after', 'words', 'long', 'than', 'first', 'been', 'call',
        'who', 'oil', 'sit', 'now', 'find', 'down', 'day', 'did', 'get',
        'come', 'made', 'may', 'part', 'over', 'new', 'sound', 'take',
        'only', 'little', 'work', 'know', 'place', 'year', 'live', 'me',
        'back', 'give', 'most', 'very', 'after', 'thing', 'our', 'just',
        'name', 'good', 'sentence', 'man', 'think', 'say', 'great', 'where',
        'help', 'through', 'much', 'before', 'line', 'right', 'too', 'means',
        'old', 'any', 'same', 'tell', 'boy', 'follow', 'came', 'want', 'show',
        'also', 'around', 'form', 'three', 'small', 'set', 'put', 'end', 'does',
        'another', 'well', 'large', 'must', 'big', 'even', 'such', 'because',
        'turn', 'here', 'why', 'ask', 'went', 'men', 'read', 'need', 'land',
        'different', 'home', 'us', 'move', 'try', 'kind', 'hand', 'picture',
        'again', 'change', 'off', 'play', 'spell', 'air', 'away', 'animal',
        'house', 'point', 'page', 'letter', 'mother', 'answer', 'found', 'study',
        'still', 'learn', 'should', 'america', 'world', 'high', 'every', 'near',
        'add', 'food', 'between', 'own', 'below', 'country', 'plant', 'last',
        'school', 'father', 'keep', 'tree', 'never', 'start', 'city', 'earth',
        'eye', 'light', 'thought', 'head', 'under', 'story', 'saw', 'left',
        'don', 'few', 'while', 'along', 'might', 'close', 'something', 'seem',
        'next', 'hard', 'open', 'example', 'begin', 'life', 'always', 'those',
        'both', 'paper', 'together', 'got', 'group', 'often', 'run', 'important',
        'until', 'children', 'side', 'feet', 'car', 'mile', 'night', 'walk',
        'white', 'sea', 'began', 'grow', 'took', 'river', 'four', 'carry',
        'state', 'once', 'book', 'hear', 'stop', 'without', 'second', 'later',
        'miss', 'idea', 'enough', 'eat', 'face', 'watch', 'far', 'indian',
        'really', 'almost', 'let', 'above', 'girl', 'sometimes', 'mountain',
        'cut', 'young', 'talk', 'soon', 'list', 'song', 'leave', 'family',
        'it', 's', 't', 've', 'll', 'm', 'd', 're', 'don', 'won', 'can',
    }
    
    words = text.split()
    # Filter out stop words and very short words
    words = [w for w in words if len(w) > 2 and w not in stop_words]
    return words


def analyze_sms_copy_by_brand():
    """Analyze SMS copy patterns for ID, CZ, and SF brands."""
    print("SMS Copy Pattern Analysis: ID, CZ, SF")
    print("=" * 70)
    
    brands_to_analyze = ['ID', 'CZ', 'SF']
    all_campaigns_by_brand = {}
    
    # Collect campaigns with SMS copy
    for brand in brands_to_analyze:
        print(f"\nProcessing {brand}...")
        csv_path = BRAND_CSV_MAPPING[brand]
        ga4_data = parse_ga4_csv(csv_path, brand)
        braze_campaigns = get_sms_campaigns_from_braze(brand, max_pages=20)
        matched = match_campaigns_to_ga4(ga4_data, braze_campaigns)
        fetch_braze_analytics_for_campaigns(matched, brand, START_DATE, END_DATE)
        matched = filter_campaigns_with_extractable_dates(matched, START_DATE, END_DATE)
        
        # Filter to brand-specific campaigns
        brand_campaigns = [c for c in matched if infer_brand_from_campaign_name(c.get('name', '')) == brand]
        
        # Fetch SMS copy
        brand_campaigns_with_copy = fetch_sms_copy_for_campaigns(brand_campaigns, brand)
        all_campaigns_by_brand[brand] = brand_campaigns_with_copy
        
        print(f"  {len(brand_campaigns_with_copy)} campaigns with SMS copy")
    
    # Analyze copy patterns for each brand
    print("\n" + "=" * 70)
    print("SMS COPY PATTERN ANALYSIS")
    print("=" * 70)
    
    for brand in brands_to_analyze:
        campaigns = all_campaigns_by_brand[brand]
        campaigns_with_sends = [c for c in campaigns if c.get('braze_sends', 0) > 0 and c.get('sms_body')]
        
        if len(campaigns_with_sends) < 4:
            print(f"\n{brand}: Not enough campaigns with SMS copy ({len(campaigns_with_sends)})")
            continue
        
        # Sort by CTR
        campaigns_sorted_by_ctr = sorted(
            campaigns_with_sends,
            key=lambda x: -x.get('braze_click_rate', 0)
        )
        
        # Split into top performers (top 25%) and bottom performers (bottom 25%)
        quarter = len(campaigns_sorted_by_ctr) // 4
        if quarter < 1:
            quarter = 1
        
        top_performers = campaigns_sorted_by_ctr[:quarter]
        bottom_performers = campaigns_sorted_by_ctr[-quarter:]
        
        print(f"\n{brand}:")
        print(f"  Total campaigns analyzed: {len(campaigns_with_sends)}")
        print(f"  Top performers (top {len(top_performers)}):")
        print(f"    Average CTR: {sum(c.get('braze_click_rate', 0) for c in top_performers) / len(top_performers) * 100:.2f}%")
        print(f"  Bottom performers (bottom {len(bottom_performers)}):")
        print(f"    Average CTR: {sum(c.get('braze_click_rate', 0) for c in bottom_performers) / len(bottom_performers) * 100:.2f}%")
        
        # Extract words from top and bottom performers
        top_words = []
        bottom_words = []
        
        for campaign in top_performers:
            body = campaign.get('sms_body', '')
            cleaned = clean_text(body)
            words = extract_words(cleaned)
            top_words.extend(words)
        
        for campaign in bottom_performers:
            body = campaign.get('sms_body', '')
            cleaned = clean_text(body)
            words = extract_words(cleaned)
            bottom_words.extend(words)
        
        # Count word frequency
        top_word_freq = Counter(top_words)
        bottom_word_freq = Counter(bottom_words)
        
        # Find words that appear more frequently in top performers
        top_unique = {}
        for word, count in top_word_freq.items():
            top_pct = count / len(top_words) if top_words else 0
            bottom_pct = bottom_word_freq.get(word, 0) / len(bottom_words) if bottom_words else 0
            if top_pct > bottom_pct * 1.5 and count >= 2:  # At least 50% more frequent and appears at least twice
                top_unique[word] = {
                    'top_count': count,
                    'top_pct': top_pct * 100,
                    'bottom_count': bottom_word_freq.get(word, 0),
                    'bottom_pct': bottom_pct * 100,
                }
        
        # Find words that appear more frequently in bottom performers
        bottom_unique = {}
        for word, count in bottom_word_freq.items():
            top_pct = top_word_freq.get(word, 0) / len(top_words) if top_words else 0
            bottom_pct = count / len(bottom_words) if bottom_words else 0
            if bottom_pct > top_pct * 1.5 and count >= 2:
                bottom_unique[word] = {
                    'top_count': top_word_freq.get(word, 0),
                    'top_pct': top_pct * 100,
                    'bottom_count': count,
                    'bottom_pct': bottom_pct * 100,
                }
        
        # Print results
        if top_unique:
            print(f"\n  Words more common in TOP performers:")
            sorted_top = sorted(top_unique.items(), key=lambda x: -x[1]['top_pct'])[:15]
            for word, stats in sorted_top:
                print(f"    '{word}': {stats['top_count']}x in top ({stats['top_pct']:.1f}%) vs {stats['bottom_count']}x in bottom ({stats['bottom_pct']:.1f}%)")
        
        if bottom_unique:
            print(f"\n  Words more common in BOTTOM performers:")
            sorted_bottom = sorted(bottom_unique.items(), key=lambda x: -x[1]['bottom_pct'])[:15]
            for word, stats in sorted_bottom:
                print(f"    '{word}': {stats['bottom_count']}x in bottom ({stats['bottom_pct']:.1f}%) vs {stats['top_count']}x in top ({stats['top_pct']:.1f}%)")
        
        # Show sample SMS copy from top performers
        print(f"\n  Sample SMS copy from TOP performers:")
        for i, campaign in enumerate(top_performers[:3], 1):
            body = campaign.get('sms_body', '')[:100]
            ctr = campaign.get('braze_click_rate', 0) * 100
            print(f"    {i}. ({ctr:.2f}% CTR) {body}...")
        
        if not top_unique and not bottom_unique:
            print(f"    (No significant word frequency differences found)")


if __name__ == "__main__":
    analyze_sms_copy_by_brand()



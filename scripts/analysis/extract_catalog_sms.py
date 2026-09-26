#!/usr/bin/env python3
"""
Extract SMS Copy for Catalog-Related Campaigns
Fetches SMS message body text from Braze API for catalog/collection campaigns
and extracts URLs pointing to the-citizenry.com/pages/...
"""

import os
import yaml
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

# Load .env for Braze API access
load_dotenv(Path(__file__).parent.parent / ".env")


def get_campaign_details_from_braze(braze_id, brand=None):
    """Fetch campaign details from Braze API."""
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
        print(f"  Error fetching from Braze for {braze_id}: {e}")
    
    return None


def extract_sms_body_from_braze_details(details):
    """Extract SMS body text from Braze campaign details."""
    if not details or "messages" not in details:
        return None
    
    for msg_key, msg_data in details.get("messages", {}).items():
        if isinstance(msg_data, dict):
            msg_channel = msg_data.get("channel", "")
            msg_type = msg_data.get("type", "")
            if msg_channel == "sms" or "sms" in msg_type.lower():
                body = msg_data.get("body", "")
                if body and body.strip():
                    return body.strip()
            if not msg_data.get("subject"):
                body = msg_data.get("body", "")
                if body and body.strip():
                    return body.strip()
    
    return None


def extract_urls_from_text(text):
    """Extract URLs from SMS text, specifically the-citizenry.com/pages/ URLs."""
    if not text:
        return []
    
    # Pattern to match URLs
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    
    # Filter for the-citizenry.com/pages/ URLs
    catalog_urls = [url for url in urls if 'the-citizenry.com/pages/' in url]
    
    return catalog_urls


def is_catalog_or_collection_campaign(campaign_name, campaign_data):
    """Check if campaign is catalog or collection related."""
    name_lower = campaign_name.lower()
    keywords = ['catalog', 'collection', 'spring', 'fall', 'summer', 'winter', 'holiday', 'july']
    
    # Check name
    if any(keyword in name_lower for keyword in keywords):
        return True
    
    # Check category/type
    category = campaign_data.get('category', '').lower()
    campaign_type = campaign_data.get('type', '').lower()
    
    if 'catalog' in category or 'catalog' in campaign_type:
        return True
    
    return False


def is_within_past_year(date_str):
    """Check if date is within the past year."""
    if not date_str:
        return False
    
    try:
        # Parse ISO format date
        if 'T' in date_str:
            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            date_obj = datetime.fromisoformat(date_str)
        
        # Make timezone-naive for comparison
        if date_obj.tzinfo:
            date_obj = date_obj.replace(tzinfo=None)
        
        one_year_ago = datetime.now() - timedelta(days=365)
        return date_obj >= one_year_ago
    except:
        return False


def extract_catalog_sms_campaigns():
    """Extract SMS copy for catalog-related campaigns."""
    print("Finding catalog/collection SMS campaigns from The Citizenry...")
    print("=" * 70)
    
    catalog_campaigns = []
    
    # Find all CZ SMS campaigns
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                campaign_data = yaml.safe_load(f)
            
            # Only process CZ SMS campaigns
            if not campaign_data:
                continue
            
            if campaign_data.get("brand") != "CZ":
                continue
            
            if campaign_data.get("channel") != "sms":
                continue
            
            campaign_name = campaign_data.get("name", yaml_file.name)
            
            # Check if it's catalog/collection related
            if not is_catalog_or_collection_campaign(campaign_name, campaign_data):
                continue
            
            # Check if sent within past year
            first_sent = campaign_data.get("dates", {}).get("first_sent")
            if not is_within_past_year(first_sent):
                continue
            
            catalog_campaigns.append({
                "file": yaml_file,
                "data": campaign_data,
                "name": campaign_name
            })
        
        except Exception as e:
            continue
    
    print(f"Found {len(catalog_campaigns)} catalog/collection SMS campaigns\n")
    
    # Fetch SMS copy for each campaign
    results = []
    
    for campaign in catalog_campaigns:
        campaign_data = campaign["data"]
        campaign_name = campaign["name"]
        braze_id = campaign_data.get("braze_id")
        first_sent = campaign_data.get("dates", {}).get("first_sent", "Unknown")
        
        print(f"Campaign: {campaign_name}")
        print(f"  Date: {first_sent}")
        print(f"  Braze ID: {braze_id}")
        
        if not braze_id:
            print("  ⚠ No Braze ID found")
            print()
            continue
        
        # Fetch from Braze
        print("  Fetching SMS copy from Braze...")
        details = get_campaign_details_from_braze(braze_id, "CZ")
        
        if not details:
            print("  ⚠ Could not fetch campaign details")
            print()
            continue
        
        sms_body = extract_sms_body_from_braze_details(details)
        
        if not sms_body:
            print("  ⚠ No SMS body found")
            print()
            continue
        
        print(f"  ✓ SMS Copy ({len(sms_body)} chars):")
        print(f"    {sms_body}")
        
        # Extract URLs
        urls = extract_urls_from_text(sms_body)
        if urls:
            print(f"  ✓ Found {len(urls)} catalog URL(s):")
            for url in urls:
                print(f"    - {url}")
        else:
            print("  ⚠ No the-citizenry.com/pages/ URLs found in SMS")
        
        results.append({
            "campaign": campaign_name,
            "date": first_sent,
            "sms_body": sms_body,
            "urls": urls
        })
        
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total campaigns processed: {len(results)}")
    
    all_urls = []
    for result in results:
        all_urls.extend(result["urls"])
    
    if all_urls:
        print(f"\nAll catalog URLs found ({len(all_urls)} total):")
        for url in sorted(set(all_urls)):
            print(f"  - {url}")
    else:
        print("\nNo catalog URLs found in SMS messages")
    
    return results


if __name__ == "__main__":
    extract_catalog_sms_campaigns()




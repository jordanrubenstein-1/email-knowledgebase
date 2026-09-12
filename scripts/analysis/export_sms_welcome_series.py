#!/usr/bin/env python3
"""
Export SMS Welcome Series to CSV

Extracts SMS welcome series data from canvas campaigns across all brands
and generates a CSV spreadsheet with one row per SMS message, sorted by brand.

Usage:
    python3 scripts/export_sms_welcome_series.py
"""

import os
import yaml
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"
OUTPUT_FILE = Path(__file__).parent.parent / "sms-welcome-series.csv"

# Load .env for Braze API access
load_dotenv(Path(__file__).parent.parent / ".env")


def get_canvas_details_from_braze(canvas_id, brand=None):
    """Fetch canvas details from Braze API."""
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
    url = f"{base_url}/canvas/details"
    params = {"canvas_id": canvas_id}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  Error fetching canvas details from Braze for {canvas_id}: {e}")
    
    return None


def get_canvas_analytics_from_braze(canvas_id, brand=None, days=30):
    """Fetch canvas analytics for the past N days."""
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
    
    # Calculate date range (past N days, max 14 days per Braze API limit)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=min(days, 14))
    
    url = f"{base_url}/canvas/data_series"
    params = {
        "canvas_id": canvas_id,
        "length": min(days, 14),
        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
        "include_step_breakdown": "true",
        "include_variant_breakdown": "true"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  Error fetching canvas analytics from Braze for {canvas_id}: {e}")
    
    return None


def has_step_been_sent_recently(canvas_id, step_id, brand, days=30):
    """Check if a canvas step has been sent at least once in the past N days."""
    analytics = get_canvas_analytics_from_braze(canvas_id, brand, days)
    if not analytics or "data" not in analytics:
        return False
    
    # Check step_stats for this step
    data = analytics.get("data", [])
    if not isinstance(data, list):
        return False
    
    for day_data in data:
        if not isinstance(day_data, dict):
            continue
        
        step_stats = day_data.get("step_stats", {})
        if not isinstance(step_stats, dict):
            continue
        
        step_data = step_stats.get(step_id, {})
        if not step_data or not isinstance(step_data, dict):
            continue
        
        # Check messages.sms for sends
        messages = step_data.get("messages", {})
        if isinstance(messages, dict):
            sms_data = messages.get("sms", [])
            if isinstance(sms_data, list):
                for variant in sms_data:
                    if isinstance(variant, dict) and variant.get("sent", 0) > 0:
                        return True
    
    return False


def extract_sms_body_from_canvas_step(step_details):
    """Extract SMS body text from a canvas step details."""
    if not step_details or "messages" not in step_details:
        return None
    
    messages = step_details.get("messages", {})
    if isinstance(messages, dict):
        for msg_key, msg_data in messages.items():
            if isinstance(msg_data, dict):
                # Check if it's an SMS message
                msg_channel = msg_data.get("channel", "")
                msg_type = msg_data.get("type", "")
                if msg_channel == "sms" or "sms" in msg_type.lower():
                    body = msg_data.get("body", "")
                    if body and body.strip():
                        return body.strip()
                # Also check for body in messages without subject (SMS won't have subject)
                if not msg_data.get("subject"):
                    body = msg_data.get("body", "")
                    if body and body.strip():
                        return body.strip()
    
    return None


def get_sms_body_from_yaml(campaign_data, step_id=None, step_name=None):
    """Get SMS body text from campaign YAML sends array."""
    if not campaign_data.get("sends"):
        return None
    
    for send in campaign_data["sends"]:
        # Check if it's an SMS send
        if send.get("channel") == "sms":
            body = send.get("body", "")
            if body and body.strip():
                # If we have step_id or step_name, try to match
                if step_id and send.get("step_id") == step_id:
                    return body.strip()
                elif step_name and send.get("name") == step_name:
                    return body.strip()
                # If no step filter, return first SMS body found
                elif not step_id and not step_name:
                    return body.strip()
    
    return None


def extract_sequence_position(step_name):
    """Extract sequence position from step name (e.g., T1, T2, T3)."""
    if not step_name:
        return None
    
    # Look for pattern like _T1_ or _T1_V1 (ID, BUR, STF format: TRG_SMS_2025_10_SF_Welcome_T1_V1)
    match = re.search(r'_T(\d+)(?:_|$)', step_name)
    if match:
        return f"T{match.group(1)}"
    
    # Look for pattern like _Welcome_T1 (CZ format: TRG_SMS_2025_04_01_CZ_D_Welcome_T1)
    match = re.search(r'Welcome_T(\d+)(?:_|$)', step_name)
    if match:
        return f"T{match.group(1)}"
    
    # Look for pattern like Step_1, Step_2, etc.
    match = re.search(r'Step[_\s](\d+)', step_name, re.IGNORECASE)
    if match:
        return f"T{match.group(1)}"
    
    return None


def is_sms_welcome_step(step_name):
    """Check if a step name indicates an SMS welcome message."""
    if not step_name:
        return False
    
    step_name_upper = step_name.upper()
    
    # Check for SMS welcome patterns:
    # - TRG_SMS_*_Welcome_* (ID, BUR, STF format: TRG_SMS_2025_10_SF_Welcome_T1_V1)
    # - TRG_SMS_*_CZ_*_Welcome_* (CZ format: TRG_SMS_2025_04_01_CZ_D_Welcome_T1)
    # - Any step with "SMS" and "Welcome" in the name
    has_sms = "TRG_SMS" in step_name_upper or "SMS" in step_name_upper
    has_welcome = "WELCOME" in step_name_upper
    
    if has_sms and has_welcome:
        return True
    
    return False


def is_sms_welcome_campaign(campaign_data):
    """Check if a campaign is an SMS welcome series."""
    if not campaign_data:
        return False
    
    # Must be a canvas
    if campaign_data.get("braze_type") != "canvas":
        return False
    
    # Check canvas_steps for SMS welcome indicators
    canvas_steps = campaign_data.get("canvas_steps", [])
    sms_welcome_steps = [
        step for step in canvas_steps
        if step.get("type") == "message" and is_sms_welcome_step(step.get("name", ""))
    ]
    
    # If we have SMS welcome steps, it's a welcome series
    if sms_welcome_steps:
        return True
    
    return False


def find_sms_welcome_campaigns():
    """Find all SMS welcome series campaigns."""
    campaigns = []
    seen_canvas_ids = set()
    
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                campaign_data = yaml.safe_load(f)
                if not campaign_data:
                    continue
                
                # Must be a canvas
                if campaign_data.get("braze_type") != "canvas":
                    continue
                
                # Check if this canvas has SMS welcome steps
                if is_sms_welcome_campaign(campaign_data):
                    canvas_id = campaign_data.get("braze_id") or campaign_data.get("id")
                    # Avoid duplicates
                    if canvas_id and canvas_id not in seen_canvas_ids:
                        seen_canvas_ids.add(canvas_id)
                        campaign_data["_filename"] = yaml_file.name
                        campaigns.append(campaign_data)
        except Exception as e:
            print(f"Error loading {yaml_file.name}: {e}")
    
    return campaigns


def extract_sms_steps_from_campaign(campaign_data):
    """Extract SMS welcome message steps from a campaign's canvas_steps."""
    sms_steps = []
    canvas_steps = campaign_data.get("canvas_steps", [])
    
    sequence_num = 0
    for step in canvas_steps:
        if step.get("type") != "message":
            continue
        
        step_name = step.get("name", "")
        # Check if it's an SMS welcome step
        if is_sms_welcome_step(step_name):
            sequence_num += 1
            sms_steps.append({
                "id": step.get("id"),
                "name": step_name,
                "sequence_num": sequence_num,
                "sequence_position": extract_sequence_position(step_name) or f"T{sequence_num}"
            })
    
    return sms_steps


def get_sms_body_for_step(campaign_data, step, brand):
    """Get SMS body text for a step, trying YAML first, then Braze API."""
    # First try YAML
    sms_body = get_sms_body_from_yaml(campaign_data, step["id"], step["name"])
    if sms_body:
        return sms_body
    
    # If not in YAML, try fetching from Braze
    braze_id = campaign_data.get("braze_id")
    if braze_id:
        print(f"  Fetching SMS copy from Braze for step: {step['name']}")
        canvas_details = get_canvas_details_from_braze(braze_id, brand)
        if canvas_details:
            # Find the step in canvas details
            steps = canvas_details.get("steps", [])
            for step_detail in steps:
                if step_detail.get("id") == step["id"]:
                    sms_body = extract_sms_body_from_canvas_step(step_detail)
                    if sms_body:
                        return sms_body
    
    return None


def export_sms_welcome_series():
    """Main function to export SMS welcome series to CSV."""
    print("Finding SMS welcome series campaigns...")
    campaigns = find_sms_welcome_campaigns()
    print(f"Found {len(campaigns)} SMS welcome series campaigns")
    
    # Collect all SMS messages
    all_sms_messages = []
    
    for campaign in campaigns:
        brand = campaign.get("brand", "Unknown")
        campaign_name = campaign.get("name", "Unknown")
        print(f"\nProcessing: {campaign_name} ({brand})")
        
        sms_steps = extract_sms_steps_from_campaign(campaign)
        print(f"  Found {len(sms_steps)} SMS message steps")
        
        for step in sms_steps:
            # Check if step has been sent in the past month
            braze_id = campaign.get("braze_id")
            has_sends = False
            
            if braze_id:
                # Try to check analytics
                has_sends = has_step_been_sent_recently(braze_id, step["id"], brand, days=30)
                
                # Fallback: check campaign last_sent date if analytics unavailable
                if not has_sends:
                    dates = campaign.get("dates", {})
                    last_sent_str = dates.get("last_sent")
                    if last_sent_str:
                        try:
                            # Parse ISO format date
                            if 'T' in last_sent_str:
                                # Handle timezone-aware dates
                                if last_sent_str.endswith('Z'):
                                    last_sent = datetime.fromisoformat(last_sent_str.replace('Z', '+00:00'))
                                elif '+' in last_sent_str or last_sent_str.count('-') >= 3:
                                    # Already has timezone
                                    last_sent = datetime.fromisoformat(last_sent_str)
                                else:
                                    # No timezone, assume UTC
                                    last_sent = datetime.fromisoformat(last_sent_str + '+00:00')
                            else:
                                last_sent = datetime.strptime(last_sent_str, "%Y-%m-%d")
                            
                            # Normalize to UTC for comparison (remove timezone info for comparison)
                            if last_sent.tzinfo:
                                last_sent = last_sent.replace(tzinfo=None)
                            
                            # Check if last sent was within past month
                            cutoff_date = datetime.now() - timedelta(days=30)
                            if last_sent >= cutoff_date:
                                has_sends = True
                                print(f"    Using campaign last_sent date: {last_sent_str}")
                        except Exception as e:
                            print(f"    Error parsing last_sent date {last_sent_str}: {e}")
                            pass
            
            if not has_sends:
                print(f"  Skipping {step['name']} - no sends in past month")
                continue
            
            sms_body = get_sms_body_for_step(campaign, step, brand)
            
            all_sms_messages.append({
                "brand": brand,
                "campaign_name": campaign_name,
                "step_name": step["name"],
                "sequence_position": step["sequence_position"],
                "sms_body_text": sms_body or "Not available"
            })
    
    # Sort by brand, then by sequence position
    def sort_key(msg):
        brand_order = {"ID": 1, "BUR": 2, "STF": 3, "CZ": 4, "HAV": 5, "TI": 6}
        brand = msg["brand"]
        brand_num = brand_order.get(brand, 99)
        # Extract numeric part from sequence position for sorting
        seq_match = re.search(r'(\d+)', msg["sequence_position"])
        seq_num = int(seq_match.group(1)) if seq_match else 999
        return (brand_num, seq_num)
    
    all_sms_messages.sort(key=sort_key)
    
    # Write to CSV
    print(f"\nWriting {len(all_sms_messages)} SMS messages to CSV...")
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Brand", "Campaign Name", "Step Name", "Sequence Position", "SMS Body Text"
        ])
        writer.writeheader()
        
        for msg in all_sms_messages:
            writer.writerow({
                "Brand": msg["brand"],
                "Campaign Name": msg["campaign_name"],
                "Step Name": msg["step_name"],
                "Sequence Position": msg["sequence_position"],
                "SMS Body Text": msg["sms_body_text"]
            })
    
    print(f"✓ Exported to {OUTPUT_FILE}")
    print(f"\nSummary by brand:")
    brand_counts = {}
    for msg in all_sms_messages:
        brand = msg["brand"]
        brand_counts[brand] = brand_counts.get(brand, 0) + 1
    
    for brand, count in sorted(brand_counts.items()):
        print(f"  {brand}: {count} SMS messages")


if __name__ == "__main__":
    export_sms_welcome_series()


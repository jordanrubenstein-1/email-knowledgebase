#!/usr/bin/env python3
"""
Backfill SMS Copy to YAML Files

Fetches SMS message body text from Braze API and stores it in campaign YAML files
for future analyses. This avoids repeated API calls.

Usage:
    python3 scripts/backfill_sms_copy.py
    python3 scripts/backfill_sms_copy.py --brand BUR
    python3 scripts/backfill_sms_copy.py --dry-run
"""

import os
import yaml
import argparse
from pathlib import Path
from dotenv import load_dotenv
import requests

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

# Load .env for Braze API access
load_dotenv(Path(__file__).parent.parent / ".env")


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
        print(f"  Error fetching from Braze for {braze_id}: {e}")
    
    return None


def extract_sms_body_from_braze_details(details):
    """Extract SMS body text from Braze campaign details."""
    if not details or "messages" not in details:
        return None
    
    for msg_key, msg_data in details.get("messages", {}).items():
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


def has_sms_copy_in_yaml(campaign_data):
    """Check if SMS copy already exists in YAML."""
    if not campaign_data.get("sends"):
        return False
    
    for send in campaign_data["sends"]:
        body = send.get("body", "")
        if body and body.strip():
            return True
    
    return False


def update_campaign_yaml(yaml_file, campaign_data, sms_body):
    """Update campaign YAML file with SMS body text."""
    # Find the first send entry and add body, or create one if needed
    if not campaign_data.get("sends"):
        campaign_data["sends"] = []
    
    # Try to find an existing SMS send to update
    updated = False
    for send in campaign_data["sends"]:
        if send.get("channel") in ("sms", "other") or not send.get("subject"):
            send["body"] = sms_body
            send["channel"] = "sms"  # Ensure channel is set
            updated = True
            break
    
    # If no suitable send found, add a new one
    if not updated:
        campaign_data["sends"].append({
            "id": "sms-body",
            "channel": "sms",
            "name": "SMS Message",
            "body": sms_body
        })
    
    # Write back to file
    with open(yaml_file, 'w') as f:
        yaml.dump(campaign_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return True


def backfill_sms_copy(brand=None, dry_run=False):
    """Backfill SMS copy for all SMS campaigns."""
    print("Loading SMS campaigns...")
    
    campaigns_processed = 0
    campaigns_updated = 0
    campaigns_skipped = 0
    campaigns_error = 0
    
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                campaign_data = yaml.safe_load(f)
            
            # Only process SMS campaigns
            if not campaign_data or campaign_data.get("channel") != "sms":
                continue
            
            # Filter by brand if specified
            if brand and campaign_data.get("brand") != brand:
                continue
            
            campaigns_processed += 1
            campaign_name = campaign_data.get("name", yaml_file.name)
            
            # Skip if already has SMS copy
            if has_sms_copy_in_yaml(campaign_data):
                campaigns_skipped += 1
                if campaigns_processed % 50 == 0:
                    print(f"  Processed {campaigns_processed} campaigns...")
                continue
            
            # Get braze_id
            braze_id = campaign_data.get("braze_id")
            if not braze_id:
                campaigns_error += 1
                continue
            
            # Fetch from Braze
            print(f"  Fetching SMS copy for: {campaign_name}")
            details = get_campaign_details_from_braze(braze_id, campaign_data.get("brand"))
            
            if not details:
                campaigns_error += 1
                continue
            
            sms_body = extract_sms_body_from_braze_details(details)
            
            if not sms_body:
                campaigns_error += 1
                continue
            
            # Update YAML file
            if not dry_run:
                update_campaign_yaml(yaml_file, campaign_data, sms_body)
                campaigns_updated += 1
                print(f"    ✓ Updated with SMS copy ({len(sms_body)} chars)")
            else:
                campaigns_updated += 1
                print(f"    [DRY RUN] Would update with SMS copy ({len(sms_body)} chars)")
            
            if campaigns_processed % 10 == 0:
                print(f"  Progress: {campaigns_processed} processed, {campaigns_updated} updated, {campaigns_skipped} skipped, {campaigns_error} errors")
        
        except Exception as e:
            print(f"  Error processing {yaml_file.name}: {e}")
            campaigns_error += 1
    
    print(f"\nSummary:")
    print(f"  Total SMS campaigns processed: {campaigns_processed}")
    print(f"  Campaigns updated: {campaigns_updated}")
    print(f"  Campaigns skipped (already had copy): {campaigns_skipped}")
    print(f"  Campaigns with errors: {campaigns_error}")
    
    if dry_run:
        print("\n  [DRY RUN] No files were modified. Run without --dry-run to update files.")


def main():
    parser = argparse.ArgumentParser(description="Backfill SMS copy from Braze into YAML files")
    parser.add_argument("--brand", help="Only process campaigns for this brand (e.g., BUR, ID, CZ)")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify files, just show what would be updated")
    args = parser.parse_args()
    
    backfill_sms_copy(brand=args.brand, dry_run=args.dry_run)


if __name__ == "__main__":
    main()








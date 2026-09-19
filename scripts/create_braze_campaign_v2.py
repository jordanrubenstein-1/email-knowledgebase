#!/usr/bin/env python3
"""
Create and send plain text email campaigns in Braze using Templates API + API-triggered campaigns.

This approach works around Braze's limitation of not supporting campaign creation via API:
1. Creates email template via Templates API
2. Triggers an existing API-triggered campaign shell
3. Can schedule sends if needed

Usage:
    uv run python scripts/create_braze_campaign_v2.py --config campaigns/campaign.yaml --brand BUR --api-campaign-id YOUR_API_CAMPAIGN_ID
    uv run python scripts/create_braze_campaign_v2.py --config campaigns/campaign.yaml --brand BUR --api-campaign-id YOUR_ID --schedule
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import yaml

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from validate_campaign_config import validate_campaign_config
from braze_template_api import create_email_template, trigger_api_campaign
from braze_campaign_api import schedule_campaign
from import_braze import normalize_brand, init_config

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load campaign configuration from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def create_and_trigger_campaign(config_path: Path, api_campaign_id: str, 
                                brand: Optional[str] = None, dry_run: bool = False,
                                schedule: bool = False) -> bool:
    """Create template and trigger API-triggered campaign.
    
    Args:
        config_path: Path to campaign config YAML
        api_campaign_id: ID of pre-created API-triggered campaign shell
        brand: Optional brand override
        dry_run: If True, validate but don't create
        schedule: If True, schedule the send (requires explicit permission)
    
    Returns:
        True if successful, False otherwise
    """
    print(f"Loading campaign configuration from {config_path}...")
    config = load_config(config_path)
    
    campaign = config.get("campaign", {})
    config_brand = campaign.get("brand", "")
    
    # Use provided brand or config brand
    if brand:
        brand = normalize_brand(brand)
    else:
        brand = normalize_brand(config_brand)
    
    if not brand:
        print("Error: Brand is required (provide via --brand or in config)")
        return False
    
    print(f"Brand: {brand}")
    print(f"Campaign: {campaign.get('name', 'Untitled')}")
    print(f"API Campaign ID: {api_campaign_id}")
    
    # Validate configuration
    print("\nValidating campaign configuration...")
    is_valid, errors, send_datetime, warnings = validate_campaign_config(config)
    
    if not is_valid:
        print("Validation failed:")
        for error in errors:
            print(f"  ✗ {error}")
        return False
    
    print("✓ Validation passed")
    
    # Show warnings if any
    if warnings:
        print("\n⚠ Performance Recommendations:")
        for warning in warnings:
            print(f"  ⚠ {warning}")
    
    if dry_run:
        print("\n[DRY RUN] Would create template and trigger campaign:")
        print(f"  Template name: {campaign.get('name')}")
        print(f"  Subject: {campaign.get('email', {}).get('subject')}")
        print(f"  API Campaign ID: {api_campaign_id}")
        print(f"  Audience: {campaign.get('audience', {}).get('id')}")
        if send_datetime:
            print(f"  Send datetime: {send_datetime.isoformat()}")
        if schedule:
            print(f"  ⚠ Would SCHEDULE campaign (requires --schedule flag)")
        else:
            print(f"  ✓ Would trigger immediately (safe mode)")
        return True
    
    # Initialize brand config
    init_config(brand)
    
    # Step 1: Create email template
    print("\nCreating email template in Braze...")
    template_id, error = create_email_template(campaign, brand)
    
    if error:
        print(f"✗ Failed to create template: {error}")
        return False
    
    print(f"✓ Email template created: {template_id}")
    
    # Step 2: Prepare audience
    audience_config = campaign.get("audience", {})
    audience_type = audience_config.get("type", "segment")
    
    if audience_type == "segment":
        audience = {"segment_id": audience_config.get("id")}
    elif audience_type == "connected_audience":
        audience = {"connected_audience_id": audience_config.get("connected_audience_id")}
    elif audience_type == "user_list":
        audience = {"external_user_ids": audience_config.get("external_user_ids", [])}
    else:
        print(f"✗ Unsupported audience type: {audience_type}")
        return False
    
    # Step 3: Prepare trigger properties (for template variables)
    email_config = campaign.get("email", {})
    trigger_properties = {
        "subject": email_config.get("subject", ""),
        "preheader": email_config.get("preheader", ""),
        "template_id": template_id
    }
    
    # Step 4: Trigger the API campaign
    print(f"\nTriggering API-triggered campaign...")
    success, error = trigger_api_campaign(
        campaign_id=api_campaign_id,
        audience=audience,
        trigger_properties=trigger_properties,
        brand=brand
    )
    
    if not success:
        print(f"✗ Failed to trigger campaign: {error}")
        return False
    
    print("✓ Campaign triggered successfully")
    
    # Step 5: Schedule if requested
    if schedule and send_datetime:
        print(f"\n⚠ SCHEDULING CAMPAIGN (explicit permission granted via --schedule flag)")
        print(f"Scheduling for {send_datetime.isoformat()}...")
        timezone = campaign.get("send", {}).get("timezone", "UTC")
        success = schedule_campaign(api_campaign_id, send_datetime, timezone, brand)
        
        if not success:
            print("✗ Failed to schedule campaign")
            return False
        
        print("✓ Campaign scheduled (will send at specified time)")
    else:
        print("\n⚠ Campaign triggered but NOT scheduled")
        print("   Campaign will send immediately to the specified audience")
        if send_datetime:
            print(f"   To schedule instead, use: --schedule")
            print(f"   Scheduled send time would be: {send_datetime.isoformat()}")
    
    print("\n" + "="*60)
    print("Campaign creation and trigger completed successfully!")
    print(f"Template ID: {template_id}")
    print(f"API Campaign ID: {api_campaign_id}")
    if schedule and send_datetime:
        print(f"✓ Scheduled for: {send_datetime.isoformat()}")
    else:
        print("⚠ Triggered immediately - check Braze dashboard for status")
    print("="*60)
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create and trigger plain text email campaigns in Braze using Templates API"
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to campaign configuration YAML file"
    )
    parser.add_argument(
        "--api-campaign-id",
        type=str,
        required=True,
        help="ID of pre-created API-triggered campaign shell in Braze"
    )
    parser.add_argument(
        "--brand",
        type=str,
        help="Brand code (overrides config if provided)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without creating template or triggering"
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Schedule the campaign send (requires explicit permission)"
    )
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        # Try relative to project root
        project_root = Path(__file__).parent.parent
        config_path = project_root / config_path
    
    # Safety check: warn if triggering without schedule
    if not args.dry_run and not args.schedule:
        print("⚠ WARNING: You are about to TRIGGER a campaign that will send emails immediately.")
        print("   This will send emails to the specified audience right away.")
        response = input("   Type 'yes' to confirm triggering: ")
        if response.lower() != 'yes':
            print("   Triggering cancelled.")
            sys.exit(0)
    
    # Safety check: warn if scheduling
    if args.schedule and not args.dry_run:
        print("⚠ WARNING: You are about to SCHEDULE a campaign that will send emails.")
        print("   This will send emails to the specified audience at the scheduled time.")
        response = input("   Type 'yes' to confirm scheduling: ")
        if response.lower() != 'yes':
            print("   Scheduling cancelled. Campaign will be triggered immediately instead.")
            args.schedule = False
    
    try:
        success = create_and_trigger_campaign(
            config_path, args.api_campaign_id, args.brand, args.dry_run, args.schedule
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

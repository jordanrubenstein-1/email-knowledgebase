#!/usr/bin/env python3
"""
Create and launch plain text email campaigns in Braze.

Usage:
    uv run python scripts/create_braze_campaign.py --config campaigns/new-campaign.yaml --brand HAV
    uv run python scripts/create_braze_campaign.py --config campaigns/new-campaign.yaml --dry-run
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import yaml

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from validate_campaign_config import validate_campaign_config, ValidationError
from braze_campaign_api import (
    create_content_block,
    create_campaign,
    schedule_campaign,
    launch_campaign,
    get_segment_info
)
from import_braze import normalize_brand, init_config

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load campaign configuration from YAML file.
    
    Args:
        config_path: Path to YAML config file
    
    Returns:
        Configuration dictionary
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def save_campaign_record(campaign_config: Dict[str, Any], braze_id: str, 
                        content_block_id: str, output_dir: Path) -> Path:
    """Save campaign record to knowledgebase.
    
    Args:
        campaign_config: Campaign configuration
        braze_id: Braze campaign ID
        content_block_id: Braze content block ID
        output_dir: Directory to save campaign record
    
    Returns:
        Path to saved file
    """
    campaign = campaign_config.get("campaign", {})
    brand = normalize_brand(campaign.get("brand", ""))
    
    # Create campaign record following existing schema
    campaign_record = {
        "id": braze_id,
        "name": campaign.get("name", ""),
        "brand": brand,
        "channel": "email",
        "category": campaign.get("category", "other"),
        "type": campaign.get("type", "announcement"),
        "theme": campaign.get("theme"),
        "braze_id": braze_id,
        "braze_type": "campaign",
        "campaign_type": "Scheduled",
        "dates": {},
        "tags": campaign.get("tags", []),
        "sends": [],
        "performance_summary": {}
    }
    
    # Add send date if available
    send_config = campaign.get("send", {})
    if send_config:
        send_date = send_config.get("date")
        if send_date:
            campaign_record["dates"]["first_sent"] = send_date
            campaign_record["dates"]["last_sent"] = send_date
    
    # Add email send info
    email_config = campaign.get("email", {})
    if email_config:
        campaign_record["sends"].append({
            "id": content_block_id,
            "channel": "email",
            "name": "Plain Text Email",
            "subject": email_config.get("subject", ""),
            "preheader": email_config.get("preheader", "")
        })
    
    # Generate filename
    from import_braze import slugify
    filename = f"{slugify(campaign.get('name', 'untitled'))}.yaml"
    filepath = output_dir / filename
    
    # Save to file
    with open(filepath, 'w') as f:
        yaml.dump(campaign_record, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return filepath


def create_campaign_workflow(config_path: Path, brand: Optional[str] = None, 
                             dry_run: bool = False, schedule: bool = False) -> bool:
    """Main workflow for creating a Braze campaign.
    
    Args:
        config_path: Path to campaign config YAML
        brand: Optional brand override
        dry_run: If True, validate but don't create
        schedule: If True, schedule the campaign after creation (requires explicit permission)
    
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
        print("\n[DRY RUN] Would create campaign with the following details:")
        print(f"  Name: {campaign.get('name')}")
        print(f"  Subject: {campaign.get('email', {}).get('subject')}")
        print(f"  Send datetime: {send_datetime.isoformat() if send_datetime else 'N/A'}")
        print(f"  Audience type: {campaign.get('audience', {}).get('type')}")
        if schedule:
            print(f"  ⚠ Would SCHEDULE campaign (requires --schedule flag)")
        else:
            print(f"  ✓ Would create but NOT schedule (safe mode)")
        return True
    
    # Initialize brand config
    init_config(brand)
    
    # Step 1: Create content block
    print("\nCreating content block in Braze...")
    content_block_id = create_content_block(campaign, brand)
    
    if not content_block_id:
        print("✗ Failed to create content block")
        return False
    
    print(f"✓ Content block created: {content_block_id}")
    
    # Step 2: Create campaign
    print("\nCreating campaign in Braze...")
    campaign_id = create_campaign(campaign, content_block_id, brand)
    
    if not campaign_id:
        print("✗ Failed to create campaign")
        return False
    
    print(f"✓ Campaign created: {campaign_id}")
    
    # Step 3: Schedule campaign (OPTIONAL - requires explicit --schedule flag)
    # NOTE: Campaign is created but NOT scheduled/sent by default for safety
    if schedule and send_datetime:
        print(f"\n⚠ SCHEDULING CAMPAIGN (explicit permission granted via --schedule flag)")
        print(f"Scheduling campaign for {send_datetime.isoformat()}...")
        timezone = campaign.get("send", {}).get("timezone", "UTC")
        success = schedule_campaign(campaign_id, send_datetime, timezone, brand)
        
        if not success:
            print("✗ Failed to schedule campaign")
            return False
        
        print("✓ Campaign scheduled (will send at specified time)")
    else:
        print("\n⚠ Campaign created but NOT scheduled or sent.")
        print("   Review the campaign in Braze dashboard before scheduling.")
        if send_datetime:
            print(f"   To schedule this campaign, use: --schedule")
            print(f"   Scheduled send time would be: {send_datetime.isoformat()}")
    
    # Step 4: Save campaign record
    print("\nSaving campaign record to knowledgebase...")
    campaigns_dir = Path(__file__).parent.parent / "campaigns"
    campaigns_dir.mkdir(exist_ok=True)
    
    try:
        record_path = save_campaign_record(config, campaign_id, content_block_id, campaigns_dir)
        print(f"✓ Campaign record saved: {record_path}")
    except Exception as e:
        print(f"⚠ Warning: Failed to save campaign record: {e}")
    
    print("\n" + "="*60)
    print("Campaign creation completed successfully!")
    print(f"Campaign ID: {campaign_id}")
    print(f"Content Block ID: {content_block_id}")
    if schedule and send_datetime:
        print(f"✓ Scheduled for: {send_datetime.isoformat()}")
    else:
        print("⚠ NOT scheduled - use --schedule flag to schedule")
    print("="*60)
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create and launch plain text email campaigns in Braze"
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to campaign configuration YAML file"
    )
    parser.add_argument(
        "--brand",
        type=str,
        help="Brand code (overrides config if provided)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without creating campaign"
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Schedule the campaign after creation (requires explicit permission)"
    )
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        # Try relative to project root
        project_root = Path(__file__).parent.parent
        config_path = project_root / config_path
    
    # Safety check: warn if scheduling
    if args.schedule and not args.dry_run:
        print("⚠ WARNING: You are about to SCHEDULE a campaign that will send emails.")
        print("   This will send emails to the specified audience at the scheduled time.")
        response = input("   Type 'yes' to confirm scheduling: ")
        if response.lower() != 'yes':
            print("   Scheduling cancelled. Campaign will be created but not scheduled.")
            args.schedule = False
    
    try:
        success = create_campaign_workflow(config_path, args.brand, args.dry_run, args.schedule)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

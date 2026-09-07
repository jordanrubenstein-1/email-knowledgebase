#!/usr/bin/env python3
"""
Create email template in Braze and provide instructions for manual campaign creation.

This script:
1. Creates the email template via Templates API
2. Provides step-by-step instructions for creating the campaign in Braze UI
3. Includes the template ID and all necessary details

Usage:
    uv run python scripts/create_template_and_guide.py --config campaigns/campaign.yaml --brand BUR
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Any
import yaml

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from validate_campaign_config import validate_campaign_config
from braze_template_api import create_email_template
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


def print_campaign_creation_guide(config: Dict[str, Any], template_id: str, brand: str):
    """Print step-by-step guide for creating campaign in Braze UI."""
    campaign = config.get("campaign", {})
    email_config = campaign.get("email", {})
    audience_config = campaign.get("audience", {})
    send_config = campaign.get("send", {})
    
    print("\n" + "="*70)
    print("CAMPAIGN CREATION GUIDE")
    print("="*70)
    print(f"\nTemplate ID: {template_id}")
    print(f"Campaign Name: {campaign.get('name')}")
    print(f"Brand: {brand}")
    
    print("\n" + "-"*70)
    print("STEP 1: Create Campaign in Braze Dashboard")
    print("-"*70)
    print("1. Go to Braze Dashboard → Campaigns → Create Campaign")
    print("2. Select 'Scheduled' or 'API-Triggered' as delivery type")
    print("3. Choose 'Email' channel")
    
    print("\n" + "-"*70)
    print("STEP 2: Select Template")
    print("-"*70)
    print(f"4. In the message composer, click 'Use Template'")
    print(f"5. Search for or select template: {campaign.get('name')}")
    print(f"   Template ID: {template_id}")
    
    print("\n" + "-"*70)
    print("STEP 3: Configure Campaign Details")
    print("-"*70)
    print(f"Campaign Name: {campaign.get('name')}")
    print(f"Subject Line: {email_config.get('subject')}")
    print(f"Preheader: {email_config.get('preheader', 'N/A')}")
    
    print("\n" + "-"*70)
    print("STEP 4: Set Audience")
    print("-"*70)
    audience_type = audience_config.get("type", "segment")
    if audience_type == "segment":
        print(f"Audience Type: Segment")
        print(f"Segment ID: {audience_config.get('id')}")
        print(f"   (In Braze: Select this segment from the audience dropdown)")
    
    print("\n" + "-"*70)
    print("STEP 5: Schedule (Optional)")
    print("-"*70)
    if send_config:
        print(f"Send Date: {send_config.get('date')}")
        print(f"Send Time: {send_config.get('time')}")
        print(f"Timezone: {send_config.get('timezone')}")
        print(f"\n   ⚠️  DO NOT schedule yet - review campaign first!")
    else:
        print("No send schedule configured")
    
    print("\n" + "-"*70)
    print("STEP 6: Review and Save")
    print("-"*70)
    print("6. Review the campaign preview")
    print("7. Check that template content displays correctly")
    print("8. Verify audience selection")
    print("9. Save the campaign (do NOT launch yet)")
    print(f"10. Note the campaign ID for future reference")
    
    print("\n" + "-"*70)
    print("STEP 7: Schedule or Send (When Ready)")
    print("-"*70)
    print("Once you've reviewed and approved:")
    print("  Option A: Schedule in Braze UI")
    print("  Option B: Use automation script to schedule:")
    print(f"    python scripts/schedule_campaign.py --campaign-id YOUR_CAMPAIGN_ID --schedule")
    
    print("\n" + "="*70)
    print(f"✓ Template created successfully: {template_id}")
    print("✓ Follow the steps above to create the campaign in Braze UI")
    print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Create email template in Braze and provide campaign creation guide"
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
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        project_root = Path(__file__).parent.parent
        config_path = project_root / config_path
    
    try:
        print(f"Loading campaign configuration from {config_path}...")
        config = load_config(config_path)
        
        campaign = config.get("campaign", {})
        config_brand = campaign.get("brand", "")
        
        # Use provided brand or config brand
        if args.brand:
            brand = normalize_brand(args.brand)
        else:
            brand = normalize_brand(config_brand)
        
        if not brand:
            print("Error: Brand is required (provide via --brand or in config)")
            sys.exit(1)
        
        print(f"Brand: {brand}")
        print(f"Campaign: {campaign.get('name', 'Untitled')}")
        
        # Validate configuration
        print("\nValidating campaign configuration...")
        is_valid, errors, _, warnings = validate_campaign_config(config)
        
        if not is_valid:
            print("Validation failed:")
            for error in errors:
                print(f"  ✗ {error}")
            sys.exit(1)
        
        print("✓ Validation passed")
        
        # Show warnings if any
        if warnings:
            print("\n⚠ Performance Recommendations:")
            for warning in warnings:
                print(f"  ⚠ {warning}")
        
        # Initialize brand config
        init_config(brand)
        
        # Create email template
        print("\nCreating email template in Braze...")
        template_id, error = create_email_template(campaign, brand)
        
        if error:
            print(f"✗ Failed to create template: {error}")
            sys.exit(1)
        
        print(f"✓ Email template created: {template_id}")
        
        # Print creation guide
        print_campaign_creation_guide(config, template_id, brand)
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

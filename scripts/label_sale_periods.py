#!/usr/bin/env python3
"""
Label all batch/blast email campaigns with sale period information.

Adds sale_period metadata to campaign YAML files indicating whether
the brand was on sale when the email was sent.
"""

import yaml
from pathlib import Path
import sys
from datetime import datetime

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent))
from utils.sale_matcher import (
    load_sale_schedules,
    get_sale_context,
)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


def is_batch_campaign(campaign: dict) -> bool:
    """Check if campaign is a batch/blast email (not triggered)."""
    # Skip canvas steps (triggered campaigns)
    if campaign.get("braze_type") == "canvas_step":
        return False
    
    # Must have sends (email campaigns)
    if not campaign.get("sends"):
        return False
    
    # Must be email channel
    if campaign.get("channel") != "email":
        return False
    
    return True


def update_campaign_with_sale_info(campaign: dict, sale_schedules: list) -> dict:
    """Add sale period information to campaign dict."""
    # Get sale context
    context = get_sale_context(campaign, sale_schedules)
    
    # Create sale_period metadata
    sale_period = {
        "during_sale": context["during_sale"],
    }
    
    if context["during_sale"]:
        sale_period["matching_sales"] = [
            {
                "id": sale.get("id"),
                "name": sale.get("name"),
                "start_date": sale.get("start_date"),
                "end_date": sale.get("end_date"),
                "discount": sale.get("discount"),
                "type": sale.get("type"),
            }
            for sale in context["matching_sales"]
        ]
        
        if context["primary_sale"]:
            sale_period["primary_sale"] = {
                "id": context["primary_sale"].get("id"),
                "name": context["primary_sale"].get("name"),
                "start_date": context["primary_sale"].get("start_date"),
                "end_date": context["primary_sale"].get("end_date"),
                "discount": context["primary_sale"].get("discount"),
                "type": context["primary_sale"].get("type"),
            }
            sale_period["sale_name"] = context["sale_name"]
            sale_period["sale_discount"] = context["sale_discount"]
            sale_period["sale_type"] = context["sale_type"]
    else:
        sale_period["matching_sales"] = []
    
    # Add to campaign
    campaign["sale_period"] = sale_period
    campaign["_sale_labeled_at"] = datetime.now().isoformat()
    
    return campaign


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Label campaigns with sale period info")
    parser.add_argument("--brand", help="Only process campaigns for this brand (e.g. TI, HAV)")
    args = parser.parse_args()

    print("Loading sale schedules...")
    sale_schedules = load_sale_schedules()
    if not sale_schedules:
        print("Warning: No sale schedules found. Run import_sale_schedules.py first.")
        return

    print(f"Loaded {len(sale_schedules)} sale periods")

    print("\nLoading campaigns...")
    campaign_files = list(CAMPAIGNS_DIR.glob("*.yaml"))
    campaign_files = [f for f in campaign_files if not f.name.startswith("_")]
    if args.brand:
        brand = args.brand.upper()
        filtered = []
        for f in campaign_files:
            try:
                with open(f) as fh:
                    c = yaml.safe_load(fh)
                if c and c.get("brand", "").upper() == brand:
                    filtered.append(f)
            except Exception:
                pass
        campaign_files = filtered
        print(f"Filtered to {len(campaign_files)} {brand} campaign files")
    else:
        print(f"Found {len(campaign_files)} campaign files")
    
    # Process campaigns
    updated = 0
    skipped = 0
    errors = 0
    
    for i, campaign_file in enumerate(campaign_files):
        if (i + 1) % 500 == 0:
            print(f"Processed {i + 1}/{len(campaign_files)} files ({updated} updated, {skipped} skipped, {errors} errors)")
        
        try:
            # Load campaign
            with open(campaign_file, 'r') as f:
                campaign = yaml.safe_load(f)
            
            if not campaign:
                skipped += 1
                continue
            
            # Only process batch/blast emails
            if not is_batch_campaign(campaign):
                skipped += 1
                continue
            
            # Check if already labeled (optional - you can remove this to re-label)
            if "sale_period" in campaign:
                # Skip if already labeled (uncomment to re-label everything)
                # skipped += 1
                # continue
                pass
            
            # Update with sale info
            campaign = update_campaign_with_sale_info(campaign, sale_schedules)
            
            # Save updated campaign
            with open(campaign_file, 'w') as f:
                yaml.dump(campaign, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            
            updated += 1
            
        except Exception as e:
            print(f"Error processing {campaign_file.name}: {e}")
            errors += 1
            continue
    
    print(f"\n{'='*60}")
    print(f"Labeling complete!")
    print(f"{'='*60}")
    print(f"Updated: {updated} campaigns")
    print(f"Skipped: {skipped} campaigns (not batch emails or already processed)")
    print(f"Errors: {errors} campaigns")
    print(f"\nSale period information added to campaign YAML files.")


if __name__ == "__main__":
    main()

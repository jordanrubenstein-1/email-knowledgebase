#!/usr/bin/env python3
"""
Test the duplicate campaign approach to see what can be updated programmatically.

This script:
1. Duplicates an existing campaign
2. Tests what fields can be updated via API
3. Reports findings

Usage:
    uv run python scripts/test_duplicate_approach.py --brand BUR --template-campaign-id CAMPAIGN_ID
"""

import sys
import argparse
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import braze_request

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


def duplicate_campaign(campaign_id: str, new_name: str, brand: str) -> Optional[str]:
    """Duplicate a campaign via Braze API.
    
    Args:
        campaign_id: ID of campaign to duplicate
        new_name: Name for the duplicated campaign
        brand: Brand code
    
    Returns:
        New campaign ID if successful, None otherwise
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    duplicate_data = {
        "campaign_id": campaign_id,
        "name": new_name
    }
    
    response_data, error = braze_post_request("campaigns/duplicate", duplicate_data, brand)
    
    if error:
        print(f"Failed to duplicate campaign: {error}")
        return None
    
    # Braze duplicate endpoint returns 202 with message "success"
    # Need to check if campaign_id is in response or fetch it another way
    if isinstance(response_data, dict):
        if "campaign_id" in response_data:
            return response_data["campaign_id"]
        elif "id" in response_data:
            return response_data["id"]
    
    # If response is just {"message": "success"}, we need to find the new campaign
    # by listing campaigns and finding the one with the new name
    # Note: 202 Accepted means the request was accepted but may take a moment to process
    print("Duplicate successful (202 Accepted), searching for new campaign ID...")
    
    # Wait a moment for the campaign to be created
    time.sleep(3)
    
    # Search through multiple pages, looking for exact name match or partial match
    page = 0
    max_pages = 5
    candidates = []
    
    while page < max_pages:
        campaigns = braze_request("campaigns/list", params={"page": page})
        if campaigns and "campaigns" in campaigns:
            for campaign in campaigns["campaigns"]:
                campaign_name = campaign.get("name", "")
                # Try exact match first
                if campaign_name == new_name:
                    print(f"Found duplicated campaign (exact name match): {campaign.get('id')}")
                    return campaign.get("id")
                # Also collect candidates with similar names (Braze might modify the name)
                if "DELETE ME" in campaign_name or "Test Duplicate" in campaign_name:
                    candidates.append((campaign.get("id"), campaign_name, campaign.get("created_at")))
        
        # Check if there are more pages
        if not campaigns or "campaigns" not in campaigns or len(campaigns.get("campaigns", [])) == 0:
            break
        page += 1
    
    # If we found candidates, return the most recently created one
    if candidates:
        # Sort by created_at (most recent first) if available
        candidates.sort(key=lambda x: x[2] if x[2] else "", reverse=True)
        best_match = candidates[0]
        print(f"Found likely duplicated campaign (name: '{best_match[1]}'): {best_match[0]}")
        return best_match[0]
    
    print(f"Warning: Could not find duplicated campaign with name '{new_name}' in first {max_pages} pages")
    print("The campaign may have been created with a different name, or it may take longer to appear.")
    print("Please check the Braze dashboard manually for the duplicated campaign.")
    return None


def get_campaign_details(campaign_id: str, brand: str) -> Optional[Dict]:
    """Get detailed campaign information."""
    brand = normalize_brand(brand)
    init_config(brand)
    
    return braze_request("campaigns/details", params={"campaign_id": campaign_id})


def test_update_campaign(campaign_id: str, updates: Dict[str, Any], brand: str, field_name: str = "") -> Tuple[bool, Optional[str]]:
    """Test if campaign can be updated via API.
    
    Args:
        campaign_id: Campaign ID to update
        updates: Dictionary of fields to update
        brand: Brand code
        field_name: Name of the field being tested (for reporting)
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    # Try different possible update endpoints
    update_endpoints = [
        "campaigns/update",
        f"campaigns/{campaign_id}/update",
        "campaigns/edit"
    ]
    
    for endpoint in update_endpoints:
        update_data = {"campaign_id": campaign_id, **updates}
        response_data, error = braze_post_request(endpoint, update_data, brand)
        
        if not error:
            print(f"    ✓ Update endpoint found: {endpoint}")
            return True, None
        elif "404" not in str(error):
            # If it's not a 404, the endpoint exists but may have validation errors
            # This is actually useful information - the endpoint exists but rejected our payload
            return False, f"Endpoint {endpoint} exists but rejected update: {error}"
    
    return False, "No update endpoint found (all returned 404)"


def main():
    parser = argparse.ArgumentParser(
        description="Test campaign duplication and update capabilities"
    )
    parser.add_argument(
        "--brand",
        type=str,
        required=True,
        help="Brand code"
    )
    parser.add_argument(
        "--template-campaign-id",
        type=str,
        help="ID of template campaign to duplicate (if not provided, will use first campaign found)"
    )
    parser.add_argument(
        "--test-campaign-id",
        type=str,
        help="ID of existing campaign to test updates on (skips duplication)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test without actually duplicating"
    )
    
    args = parser.parse_args()
    
    brand = normalize_brand(args.brand)
    init_config(brand)
    
    # Get template campaign ID
    if args.template_campaign_id:
        template_id = args.template_campaign_id
    else:
        print("Finding a campaign to use as template...")
        campaigns = braze_request("campaigns/list", params={"page": 0})
        if not campaigns or "campaigns" not in campaigns or len(campaigns["campaigns"]) == 0:
            print("No campaigns found. Please create a template campaign first or provide --template-campaign-id")
            sys.exit(1)
        
        template_id = campaigns["campaigns"][0]["id"]
        template_name = campaigns["campaigns"][0].get("name", "Unknown")
        print(f"Using campaign: {template_name} (ID: {template_id})")
    
    # Get template campaign details
    print(f"\nFetching template campaign details...")
    template_details = get_campaign_details(template_id, brand)
    if template_details:
        print(f"✓ Template campaign found")
        print(f"  Name: {template_details.get('name', 'N/A')}")
        print(f"  Type: {template_details.get('campaign_type', 'N/A')}")
    else:
        print(f"✗ Could not fetch template campaign details")
        sys.exit(1)
    
    # Check if user wants to test on existing campaign
    if args.test_campaign_id:
        new_campaign_id = args.test_campaign_id
        print(f"\nUsing existing campaign for testing: {new_campaign_id}")
        print("(Skipping duplication step)")
    else:
        if args.dry_run:
            print("\n[DRY RUN] Would test duplication and update")
            print(f"  Template ID: {template_id}")
            print(f"  New name: Test Duplicate Campaign")
            return
        
        # Test duplication
        print(f"\nTesting campaign duplication...")
        new_campaign_id = duplicate_campaign(
            template_id,
            "Test Duplicate Campaign - DELETE ME",
            brand
        )
        
        if not new_campaign_id:
            print("✗ Duplication failed")
            print("\nTip: You can use --test-campaign-id <ID> to test updates on an existing campaign")
            sys.exit(1)
        
        print(f"✓ Campaign duplicated successfully!")
        print(f"  New campaign ID: {new_campaign_id}")
    
    # Get campaign details to understand structure
    print(f"\nFetching duplicated campaign details...")
    campaign_details = get_campaign_details(new_campaign_id, brand)
    if campaign_details:
        print(f"✓ Campaign details retrieved")
        # Print some key info for reference
        if "messages" in campaign_details:
            messages = campaign_details.get("messages", {})
            if "email" in messages:
                email_msg = messages["email"]
                print(f"  Current subject: {email_msg.get('subject', 'N/A')}")
                print(f"  Current preheader: {email_msg.get('preheader', 'N/A')}")
        if "audience" in campaign_details:
            audience = campaign_details.get("audience", {})
            print(f"  Current audience type: {audience.get('audience_type', 'N/A')}")
            if "segment_id" in audience:
                print(f"  Current segment_id: {audience.get('segment_id', 'N/A')}")
    
    # Test what can be updated
    print(f"\n" + "="*70)
    print("TESTING UPDATE ENDPOINT")
    print("="*70)
    
    results = {}
    
    # Test 1: Subject line
    print(f"\n1. Testing Subject Line Update...")
    subject_updates = [
        {"subject": "Test Updated Subject Line"},
        {"messages": {"email": {"subject": "Test Updated Subject Line"}}},
        {"email_subject": "Test Updated Subject Line"},
    ]
    for i, update_test in enumerate(subject_updates, 1):
        print(f"   Attempt {i}: {list(update_test.keys())[0]}")
        success, error = test_update_campaign(new_campaign_id, update_test, brand, "subject")
        if success:
            print(f"    ✓ SUCCESS: Can update subject line using: {list(update_test.keys())[0]}")
            results["subject"] = {"success": True, "method": list(update_test.keys())[0]}
            break
        else:
            print(f"    ✗ Failed: {error}")
            if i == len(subject_updates):
                results["subject"] = {"success": False, "error": error}
    
    # Test 2: Preheader
    print(f"\n2. Testing Preheader Update...")
    preheader_updates = [
        {"preheader": "Test Updated Preheader"},
        {"messages": {"email": {"preheader": "Test Updated Preheader"}}},
        {"email_preheader": "Test Updated Preheader"},
    ]
    for i, update_test in enumerate(preheader_updates, 1):
        print(f"   Attempt {i}: {list(update_test.keys())[0]}")
        success, error = test_update_campaign(new_campaign_id, update_test, brand, "preheader")
        if success:
            print(f"    ✓ SUCCESS: Can update preheader using: {list(update_test.keys())[0]}")
            results["preheader"] = {"success": True, "method": list(update_test.keys())[0]}
            break
        else:
            print(f"    ✗ Failed: {error}")
            if i == len(preheader_updates):
                results["preheader"] = {"success": False, "error": error}
    
    # Test 3: Audience (segment_id)
    print(f"\n3. Testing Audience/Segment Update...")
    # First, get a valid segment ID to test with
    segments = braze_request("segments/list", params={"page": 0})
    test_segment_id = None
    if segments and "segments" in segments and len(segments["segments"]) > 0:
        test_segment_id = segments["segments"][0].get("id")
        print(f"   Using test segment: {segments['segments'][0].get('name', 'Unknown')} (ID: {test_segment_id})")
    
    if test_segment_id:
        audience_updates = [
            {"segment_id": test_segment_id},
            {"audience": {"segment_id": test_segment_id}},
            {"audience": {"audience_type": "segment", "segment_id": test_segment_id}},
        ]
        for i, update_test in enumerate(audience_updates, 1):
            print(f"   Attempt {i}: {list(update_test.keys())[0]}")
            success, error = test_update_campaign(new_campaign_id, update_test, brand, "audience")
            if success:
                print(f"    ✓ SUCCESS: Can update audience using: {list(update_test.keys())[0]}")
                results["audience"] = {"success": True, "method": list(update_test.keys())[0]}
                break
            else:
                print(f"    ✗ Failed: {error}")
                if i == len(audience_updates):
                    results["audience"] = {"success": False, "error": error}
    else:
        print(f"    ⚠ Skipped: No segments found to test with")
        results["audience"] = {"success": False, "error": "No segments available for testing"}
    
    # Test 4: Send date/time (schedule)
    print(f"\n4. Testing Schedule/Send Date Update...")
    from datetime import datetime, timedelta
    future_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    schedule_updates = [
        {"schedule": {"time": future_date, "in_local_time": False}},
        {"schedule": {"time": future_date, "in_local_time": True, "timezone": "America/New_York"}},
        {"send_at": future_date},
        {"scheduled_time": future_date},
    ]
    for i, update_test in enumerate(schedule_updates, 1):
        print(f"   Attempt {i}: {list(update_test.keys())[0]}")
        success, error = test_update_campaign(new_campaign_id, update_test, brand, "schedule")
        if success:
            print(f"    ✓ SUCCESS: Can update schedule using: {list(update_test.keys())[0]}")
            results["schedule"] = {"success": True, "method": list(update_test.keys())[0]}
            break
        else:
            print(f"    ✗ Failed: {error}")
            if i == len(schedule_updates):
                results["schedule"] = {"success": False, "error": error}
    
    # Print summary
    print(f"\n" + "="*70)
    print("TEST RESULTS SUMMARY")
    print("="*70)
    print(f"✓ Duplication works: {new_campaign_id}")
    print(f"\nUpdate Endpoint Test Results:")
    
    for field, result in results.items():
        if result.get("success"):
            print(f"  ✓ {field.upper()}: Can be updated via API (method: {result.get('method', 'unknown')})")
        else:
            error = result.get("error", "Unknown error")
            if "404" in error or "No update endpoint found" in error:
                print(f"  ✗ {field.upper()}: Update endpoint does not exist")
            else:
                print(f"  ✗ {field.upper()}: Update failed - {error}")
    
    print(f"\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print(f"1. Check Braze dashboard for campaign: {new_campaign_id}")
    print(f"2. Verify any successful updates were actually applied")
    print(f"3. If updates failed, check Braze API documentation for correct payload format")
    print(f"4. Consider alternative approaches if update endpoint doesn't support needed fields")
    print("="*70)


if __name__ == "__main__":
    main()

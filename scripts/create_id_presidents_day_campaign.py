#!/usr/bin/env python
"""Create President's Day Early Access campaign for Interior Define.

This script uses Playwright to automate campaign creation in Braze.
Run with: source .venv_run/bin/activate && python scripts/create_id_presidents_day_campaign.py

Usage:
  --skip-filter   Skip audience filter step
  --skip-schedule Skip schedule step
  --dry-run       Don't save the campaign
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add the MCP server source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-servers/braze/src"))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def main():
    """Create the President's Day Early Access campaign."""
    
    parser = argparse.ArgumentParser(description="Create President's Day campaign")
    parser.add_argument("--skip-filter", action="store_true", help="Skip audience filter")
    parser.add_argument("--skip-schedule", action="store_true", help="Skip scheduling")
    parser.add_argument("--dry-run", action="store_true", help="Don't save campaign")
    parser.add_argument("--screenshot", action="store_true", help="Take screenshot on completion")
    args = parser.parse_args()
    
    # Import after path setup
    from braze_mcp.browser.campaign import create_campaign
    from braze_mcp.browser.session import SessionManager
    
    # Campaign details
    brand = "ID"  # Interior Define
    name = "P_EM_2026_02_06_ID_Sale_Presidents_Day_Early_Access_PT"
    subject = "Early Access: President's Day Sale Starts Now"
    preheader = "25% off under $3K, 30% off over $3K - Presidents Day Weekend only"
    
    # Plain text body
    body_plain_text = """Hi there,

You're getting early access to our President's Day Sale!

Starting NOW through Presidents Day Weekend (2/14 - 2/16):

• 25% off orders under $3,000
• 30% off orders $3,000+
• 35% off orders $4,000+ (Presidents Day Weekend Only 2/14-2/16)

Discount applied automatically in cart.

Shop now at interiordefine.com

- The Interior Define Team"""

    # Schedule: Friday 2/6 at 7:15am Eastern
    schedule_date = None if args.skip_schedule else "2026-02-06"
    schedule_time = None if args.skip_schedule else "07:15"
    schedule_timezone = "America/New_York"
    
    # Audience filter: test email only
    audience_filter_attribute = None if args.skip_filter else "email"
    audience_filter_value = None if args.skip_filter else "jordan.rubenstein+20260129@havenly.com"
    
    print(f"Creating campaign: {name}")
    print(f"Brand: {brand}")
    print(f"Subject: {subject}")
    if not args.skip_schedule:
        print(f"Schedule: {schedule_date} at {schedule_time} {schedule_timezone}")
    else:
        print("Schedule: SKIPPED")
    if not args.skip_filter:
        print(f"Audience filter: email equals {audience_filter_value}")
    else:
        print("Audience filter: SKIPPED")
    print(f"Dry run: {args.dry_run}")
    print()
    
    manager = SessionManager.get_instance()
    
    try:
        # Run in visible mode so you can watch the automation
        result = await create_campaign(
            brand=brand,
            name=name,
            subject=subject,
            preheader=preheader,
            body_plain_text=body_plain_text,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            schedule_timezone=schedule_timezone,
            audience_filter_attribute=audience_filter_attribute,
            audience_filter_operator="equals",
            audience_filter_value=audience_filter_value,
            dry_run=args.dry_run,
            headless=False,  # Show the browser window
        )
        
        print("Result:")
        print(result)
        
        if result.get("success"):
            print("\n✅ Campaign created successfully!")
        else:
            print("\n❌ Campaign creation failed")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Take screenshot on error
        try:
            page = manager.page
            if page:
                screenshot_path = "/tmp/braze_error_screenshot.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"\n📸 Screenshot saved to: {screenshot_path}")
        except Exception as ss_err:
            print(f"Could not take screenshot: {ss_err}")
            
    finally:
        # Keep browser open so user can see result and manually complete if needed
        print("\nBrowser will stay open for 30 seconds...")
        print("You can manually complete any remaining steps.")
        await asyncio.sleep(30)
        
        # Close the browser session
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())

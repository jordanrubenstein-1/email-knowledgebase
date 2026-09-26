#!/usr/bin/env python3
"""
Test script: create a draft BUR PT campaign with the 'Memorial Day Canvas Test Group'
exclusion filter group to verify the audience filter is wired correctly.

The campaign is saved as a DRAFT — it will NOT be scheduled or sent.

Usage:
    uv run python scripts/test_bur_exclusion_filter.py
    uv run python scripts/test_bur_exclusion_filter.py --headless
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from braze_automation.login import (
    login,
    save_session,
    select_workspace,
    create_context_with_session,
)
from braze_automation.build_pt_campaign import (
    navigate_to_campaigns,
    start_email_campaign,
    set_campaign_name,
    configure_email_content,
    configure_target_audience,
    save_as_draft,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

CAMPAIGN_NAME = "P_EM_2026_05_12_BW_PT_Test_Exclusion_Filter"
SUBJECT = "[TEST] Exclusion filter test — do not send"
PREHEADER = "Verifying Memorial Day Canvas Test Group exclusion filter"
BRAND = "BUR"

# BUR engaged audience with the exclusion filter group
AUDIENCE_CONFIG = {
    "type": "all_users_with_filters",
    "segment": "AM List VIP",
    "filters": [
        {"type": "segment", "name": "202411 Send List", "op": "or"},
        {"type": "segment", "name": "Microsoft Domains - 30 Day Engaged", "op": "or"},
        {"type": "segment", "name": "Grow Leads - Eligible for Marketing", "op": "or"},
        {"type": "segment", "name": "Pro Plus Giveaway Leads", "op": "or"},
    ],
    "exclusion_filter_groups": [
        {"name": "Memorial Day Canvas Test Group"},
    ],
}

HTML_BODY = """<html>
<head></head>
<body style="font-family: Arial, sans-serif; font-size: 16px; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
<p>Hi {{${first_name} | default: 'there'}},</p>
<p>This is a test email to verify the audience exclusion filter is working correctly. Please do not send.</p>
<p>The campaign should exclude users in the "Memorial Day Canvas Test Group" segment.</p>
<p>Burrow</p>
<br>
<p style="font-size: 12px; color: #999;">
  <a href="{{${set_user_to_unsubscribed_url}}}" style="color: #999;">Unsubscribe</a>
</p>
</body>
</html>"""


async def run_test(headless: bool = False) -> bool:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            logger.info("Logging in to Braze...")
            await login(page)
            await save_session(context)

            logger.info(f"Selecting workspace: {BRAND}")
            await select_workspace(page, BRAND)

            logger.info("Navigating to Campaigns...")
            await navigate_to_campaigns(page, brand=BRAND)

            logger.info("Starting campaign creation...")
            await start_email_campaign(page)

            logger.info(f"Setting campaign name: {CAMPAIGN_NAME}")
            await set_campaign_name(page, CAMPAIGN_NAME)

            logger.info("Configuring email content...")
            await configure_email_content(
                page,
                subject=SUBJECT,
                preheader=PREHEADER,
                html_body=HTML_BODY,
            )

            logger.info("Configuring target audience...")
            await configure_target_audience(page, AUDIENCE_CONFIG)

            # Screenshot to verify the audience filter
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = PROJECT_ROOT / f"debug_exclusion_filter_test_{timestamp}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Screenshot saved: {screenshot_path}")

            logger.info("Saving as draft...")
            await save_as_draft(page, dry_run=False)

            logger.info("=" * 60)
            logger.info("TEST CAMPAIGN CREATED AS DRAFT")
            logger.info(f"  Name: {CAMPAIGN_NAME}")
            logger.info(f"  Brand: {BRAND}")
            logger.info(f"  Base segment: AM List VIP")
            logger.info(f"  Exclusion filter group: NOT IN 'Memorial Day Canvas Test Group'")
            logger.info(f"  Screenshot: {screenshot_path}")
            logger.info("  Check the Braze dashboard to verify the filter group is correct.")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"Test failed: {e}")
            import traceback
            traceback.print_exc()
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                err_path = PROJECT_ROOT / f"debug_exclusion_filter_error_{ts}.png"
                await page.screenshot(path=str(err_path), full_page=True)
                logger.info(f"Error screenshot saved: {err_path}")
            except Exception:
                pass
            return False
        finally:
            await browser.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test BUR exclusion filter group campaign")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    args = parser.parse_args()

    success = asyncio.run(run_test(headless=args.headless))
    sys.exit(0 if success else 1)

"""Test script: duplicate P_EM_2026_05_29_BW_D_Clearance_Final_Days and set BW
full_file audience with Memorial Day Canvas Test Group excluded.

Exercises the three fixes from 2026-05-26:
  1. _clear_audience_selection now removes Exclusion Groups + filter group containers
  2. _add_audience_filter uses .first (not .last) for the Search filter... picker
  3. configure_audience_designed now calls _add_exclusion_filter_group + _set_variant1_to_100
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_push_campaign import navigate_to_campaigns_list, wait_for_campaign_editor
from build_designed_campaign import (
    search_and_duplicate_email_campaign,
    _clear_audience_selection,
    configure_audience_designed,
)
from build_pt_campaign import load_brand_config, get_brand_entry, save_as_draft

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger(__name__)

REF_CAMPAIGN = "P_EM_2026_05_29_BW_D_Clearance_Final_Days"
BRAND = "BUR"


async def run():
    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    audience_config = brand_entry["audiences"]["full_file"]
    logger.info(f"Audience config: {audience_config}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        # --- Duplicate the reference campaign ---
        await navigate_to_campaigns_list(page, brand=BRAND)
        duplicated = await search_and_duplicate_email_campaign(page, REF_CAMPAIGN, BRAND)
        if not duplicated:
            logger.error(f"Could not duplicate: {REF_CAMPAIGN}")
            await browser.close()
            return

        await wait_for_campaign_editor(page)
        logger.info(f"Campaign editor loaded. URL: {page.url}")
        # Braze names the copy "Copy of <original>" automatically — leave it as-is.

        # --- Configure audience (the part we're testing) ---
        logger.info("Configuring audience...")
        await configure_audience_designed(
            page,
            desired_segment_type="full_file",
            ref_segment_type=None,  # treat ref as unknown so clearing always runs
            brand=BRAND,
        )

        # --- Save as draft ---
        logger.info("Saving as draft...")
        await save_as_draft(page, dry_run=False)
        logger.info(f"Done. Final URL: {page.url}")

        input("\nInspect the campaign in Braze, then press Enter to close the browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())

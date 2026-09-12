#!/usr/bin/env python3
"""
One-off: Check UTM Template for {{ product_url }} in the CZ Back in Stock
campaign (P_EM_2026_06_08_CZ_D_Back_In_Stock).

The initial build used _apply_utm_template which selected the UTM Template
dropdown but didn't run the final-pass per-row checkbox check. This script
opens the campaign's Link Management and checks any unchecked checkboxes.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in
from build_pt_campaign import save_as_draft

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns/"
    "6a164346f903be00812a2061/666672a4d8965b005ac6c1bd"
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)

        # Navigate to campaign compose step
        logger.info(f"Navigating to campaign: {CAMPAIGN_URL}")
        await page.goto(CAMPAIGN_URL, wait_until="load", timeout=20000)
        await page.wait_for_timeout(2000)

        # Click Variant 1 tab
        for sel in [
            page.get_by_role("tab", name="Variant 1"),
            page.get_by_text("Variant 1", exact=True),
        ]:
            try:
                if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                    await sel.first.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Selected Variant 1")
                    break
            except Exception:
                continue

        # Scroll to expose Edit message button
        await page.evaluate("window.scrollBy(0, 1500)")
        await page.wait_for_timeout(1000)

        # Click Edit message
        opened = False
        for sel in [
            page.get_by_role("button", name="Edit message"),
            page.locator("button:has-text('Edit message')"),
        ]:
            try:
                if await sel.count() > 0 and await sel.first.is_visible(timeout=5000):
                    await sel.first.scroll_into_view_if_needed()
                    await sel.first.click()
                    await page.wait_for_timeout(2000)
                    logger.info("Opened HTML editor modal")
                    opened = True
                    break
            except Exception:
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(500)

        if not opened:
            logger.error("Could not open Edit message modal")
            await browser.close()
            return

        # Open Link Management
        try:
            link_mgmt = page.get_by_text("Link Management", exact=True).first
            await link_mgmt.wait_for(state="visible", timeout=5000)
            await link_mgmt.click()
            await page.wait_for_timeout(2000)
            logger.info("Opened Link Management")
        except Exception as e:
            logger.error(f"Could not open Link Management: {e}")
            await browser.close()
            return

        # Header "select all" checkboxes (static URLs)
        header_checkboxes = page.locator(
            "thead input[type='checkbox'], "
            "th input[type='checkbox'], "
            "[role='columnheader'] input[type='checkbox']"
        )
        hc_count = await header_checkboxes.count()
        if hc_count > 0:
            for i in range(hc_count):
                cb = header_checkboxes.nth(i)
                try:
                    if await cb.is_visible() and not await cb.is_checked():
                        await cb.click()
                        await page.wait_for_timeout(300)
                        logger.info(f"Checked header checkbox {i}")
                except Exception:
                    pass

        # Final pass: per-row checkboxes (covers {{ product_url }})
        await page.wait_for_timeout(500)
        all_cbs = page.locator("input[type='checkbox']")
        fixed = 0
        for i in range(await all_cbs.count()):
            cb = all_cbs.nth(i)
            try:
                if await cb.is_visible() and not await cb.is_checked():
                    await cb.click()
                    await page.wait_for_timeout(200)
                    fixed += 1
                    logger.info(f"Checked per-row checkbox {i}")
            except Exception:
                pass

        if fixed:
            logger.info(f"Checked {fixed} previously-unchecked link checkbox(es)")
        else:
            logger.info("All link checkboxes were already checked — nothing to do")

        # Debug screenshot
        try:
            dbg = str(Path(__file__).parent / "debug_cz_bis_link_mgmt_fixed.png")
            await page.screenshot(path=dbg, full_page=False)
            logger.info(f"Screenshot: {dbg}")
        except Exception:
            pass

        # Close modal and save
        for done_sel in [
            page.get_by_role("button", name="Done", exact=True),
            page.locator("button:has-text('Done')").last,
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                    await done_sel.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Closed editor modal")
                    break
            except Exception:
                continue

        await save_as_draft(page, dry_run=False)
        logger.info("Saved as draft")

        await context.close()
        await browser.close()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

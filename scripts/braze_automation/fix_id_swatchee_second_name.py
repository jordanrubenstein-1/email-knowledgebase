#!/usr/bin/env python3
"""Restore the correct campaign name on the ID Swatchee Second-Send #1 draft.

The prior edit (edit_pt_id_swatchee_second_20260825.py) fixed the body/subject
but a stale "Campaign Name" field value present in the edit form ("P_EM_2026_08_25_ID_PT_Labor_Day_Swatchees")
got resubmitted on Save Draft, overwriting the correct name
"P_EM_2026_08_25_ID_PT_Swatchee_Second_1". This script only fixes the name field.

Braze: https://dashboard-07.braze.com/engagement/campaigns/6a80df47bb72820088dda11e/6666726b459b5e0059d7d687
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

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import get_campaign_url_from_page, save_as_draft
from build_push_campaign import wait_for_campaign_editor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND = "ID"
CAMPAIGN_ID = "6a80df47bb72820088dda11e"
WORKSPACE_ID = "6666726b459b5e0059d7d687"
CORRECT_NAME = "P_EM_2026_08_25_ID_PT_Swatchee_Second_1"
SCRIPT_DIR = Path(__file__).parent


async def _debug(page, name: str) -> None:
    try:
        path = str(SCRIPT_DIR / f"debug_id_name_fix_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info("Screenshot: %s", path)
    except Exception:
        pass


async def fix_name() -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await ensure_logged_in(page)
            await select_workspace(page, BRAND)

            campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
            await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            await _debug(page, "01_after_nav")

            for sel in [
                page.get_by_role("button", name="Edit Draft"),
                page.get_by_role("link", name="Edit Draft"),
                page.locator("a:has-text('Edit Draft')"),
                page.locator("button:has-text('Edit Draft')"),
            ]:
                try:
                    if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                        await sel.first.click()
                        await page.wait_for_timeout(3000)
                        logger.info("Clicked 'Edit Draft'")
                        break
                except Exception:
                    continue

            try:
                await wait_for_campaign_editor(page)
            except Exception as e:
                logger.warning("wait_for_campaign_editor: %s", e)

            await _debug(page, "02_compose_overview")

            name_input = page.get_by_label("Campaign Name")
            if await name_input.count() == 0:
                name_input = page.locator("input").filter(has_text="").first
            current_value = await name_input.input_value()
            logger.info("Current Campaign Name field value: %r", current_value)

            await name_input.click()
            await page.keyboard.press("Meta+a")
            await page.keyboard.type(CORRECT_NAME)
            await page.wait_for_timeout(300)
            new_value = await name_input.input_value()
            logger.info("New Campaign Name field value: %r", new_value)
            await _debug(page, "03_name_filled")

            if new_value != CORRECT_NAME:
                raise RuntimeError(f"Campaign Name field shows {new_value!r}, expected {CORRECT_NAME!r} — aborting before save")

            await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            braze_url = get_campaign_url_from_page(page.url) or page.url
            logger.info("Saved. URL: %s", braze_url)
            await _debug(page, "04_final")
            return braze_url
        finally:
            await context.close()
            await browser.close()


def main():
    url = asyncio.run(fix_name())
    print(f"\nName fix complete. Campaign: {url}")


if __name__ == "__main__":
    main()

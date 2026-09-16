#!/usr/bin/env python3
"""
Fix: set image src + link on the empty top row of the Memorial Day draft.

Row 2 (2.png → #packages-section) is already correct.
Row 1 is an empty placeholder that needs img1_cdn → homepage.

Usage:
    uv run python scripts/braze_automation/fix_top_image_memorial_day.py
    uv run python scripts/braze_automation/fix_top_image_memorial_day.py --no-headless
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session
from build_designed_campaign import _close_dnd_editor
from build_pt_campaign import save_as_draft

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns/"
    "6a028cd67634da008588174e/664223fb71bcf3005760dfc2"
    "?locale=en&campaignName=P_EM_2026_05_15_HAV_PC_D_Memorial_Day_Sale_Reminder&page=1"
)
IMG1_CDN = "https://braze-images.com/appboy/communication/assets/image_assets/images/6a029012cfb37800832a056e/original.png"
LINK1 = "https://havenly.com/"

DEBUG_DIR = Path(__file__).parent


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _screenshot(page: Page, label: str) -> None:
    try:
        path = DEBUG_DIR / f"debug_fix_top_{label}_{_ts()}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot: {path.name}")
    except Exception as e:
        logger.debug(f"Screenshot failed: {e}")


async def _get_bee_frame(page: Page):
    for frame in page.frames:
        if "getbee.io" in frame.url:
            return frame
    return None


async def run(headless: bool = True) -> bool:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await create_context_with_session(browser)
        page = await context.new_page()

        try:
            # Navigate to campaign
            logger.info("Navigating to campaign...")
            await page.goto(CAMPAIGN_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            # Click Compose step if not already there
            for compose_sel in [
                page.get_by_role("link", name="Compose"),
                page.locator("a:has-text('Compose')"),
                page.locator("button:has-text('Compose')"),
            ]:
                try:
                    if await compose_sel.count() > 0 and await compose_sel.first.is_visible():
                        await compose_sel.first.click()
                        await page.wait_for_timeout(3000)
                        logger.info("Clicked Compose")
                        break
                except Exception:
                    continue
            await _screenshot(page, "00_compose")

            # Open DnD editor
            for sel in [
                page.get_by_role("button", name="Edit message"),
                page.locator("button:has-text('Edit message')"),
                page.get_by_role("link", name="Edit message"),
            ]:
                try:
                    if await sel.count() > 0 and await sel.first.is_visible():
                        await sel.first.click()
                        await page.wait_for_timeout(5000)
                        logger.info("DnD editor opened")
                        break
                except Exception:
                    continue
            await _screenshot(page, "01_editor_open")

            bee_frame = await _get_bee_frame(page)
            if bee_frame is None:
                logger.error("BEE frame not found")
                return False

            # Click the empty top image block
            # Strategy 1: find content-labels--image (the label overlay on empty image blocks)
            clicked = False
            for sel in [
                "[class*='content-labels--image']",
                "[class*='ContentLabels'][class*='image']",
                "[class*='bee-image'][class*='content-labels']",
            ]:
                try:
                    el = bee_frame.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.wait_for_timeout(2000)
                        logger.info(f"Clicked via {sel!r}")
                        clicked = True
                        break
                except Exception as e:
                    logger.debug(f"{sel!r}: {e}")

            # Strategy 2: click near the TOP of row 1 (y + 50, not center)
            if not clicked:
                bee_frame = await _get_bee_frame(page)
                for row_sel in [
                    "[aria-label*='row 1 out of']",
                    "[class*='row-container-outer--first']",
                    "[class*='row-container-outer']:first-of-type",
                ]:
                    try:
                        el = bee_frame.locator(row_sel)
                        if await el.count() > 0:
                            box = await el.first.bounding_box()
                            if box:
                                cx = box["x"] + box["width"] / 2
                                cy = box["y"] + 50  # near top, not center
                                await page.mouse.click(cx, cy)
                                await page.wait_for_timeout(2000)
                                logger.info(f"Clicked row 1 at ({cx:.0f},{cy:.0f}) via {row_sel!r}")
                                clicked = True
                                break
                    except Exception as e:
                        logger.debug(f"{row_sel!r}: {e}")

            await _screenshot(page, "02_top_block_clicked")

            # Check what's in the properties panel
            bee_frame = await _get_bee_frame(page)
            if bee_frame is None:
                logger.error("BEE frame gone")
                return False

            await page.wait_for_timeout(1000)
            try:
                all_text = bee_frame.locator("input[type='text']")
                count = await all_text.count()
                logger.info(f"Inputs: {count}")
                for i in range(min(count, 5)):
                    v = await all_text.nth(i).input_value()
                    logger.info(f"  text[{i}] = {v[:80]!r}")
            except Exception as e:
                logger.debug(f"Input dump failed: {e}")

            # Set img1 src (text[0]) and link (text[2])
            src_set = False
            link_set = False
            try:
                all_text = bee_frame.locator("input[type='text']")
                count = await all_text.count()

                if count >= 1:
                    inp = all_text.nth(0)
                    await inp.click()
                    await inp.fill(IMG1_CDN)
                    await inp.press("Tab")
                    await page.wait_for_timeout(500)
                    src_set = True
                    logger.info(f"Src set → {IMG1_CDN[:60]}")

                if count >= 3:
                    inp = all_text.nth(2)
                    await inp.click()
                    await inp.fill(LINK1)
                    await inp.press("Tab")
                    await page.wait_for_timeout(500)
                    link_set = True
                    logger.info(f"Link set → {LINK1}")

            except Exception as e:
                logger.error(f"Set src/link failed: {e}")

            await _screenshot(page, "03_img1_set")
            logger.info(f"src_set={src_set}, link_set={link_set}")

            # Close editor
            await _close_dnd_editor(page)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "04_editor_closed")

            # Save draft
            saved = await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "05_saved")

            logger.info(f"Done — src_set={src_set}, link_set={link_set}, saved={saved}")
            return src_set and link_set and saved

        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await _screenshot(page, "error")
            return False
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True)
    args = parser.parse_args()
    success = asyncio.run(run(headless=args.headless))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

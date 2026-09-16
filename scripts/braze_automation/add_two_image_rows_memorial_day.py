#!/usr/bin/env python3
"""
One-off: add a second image row to P_EM_2026_05_15_HAV_PC_D_Memorial_Day_Sale_Reminder.

The draft was built from a 1-image reference campaign. The design has 2 slices:
  1.png → top row, links to homepage
  2.png → bottom row, links to https://havenly.com/#packages-section

Steps:
  1. Download 1.png and 2.png from Google Drive
  2. Upload both to Braze media library → get CDN URLs
  3. Navigate to the existing draft
  4. Open DnD editor
  5. Drag an Image block from the CONTENT sidebar to the top of the canvas
  6. Click the new (empty) top block → set src=img1_cdn, link=homepage
  7. Click the original (now 2nd) image → set src=img2_cdn, link=#packages-section
  8. Close editor → Save draft

Usage:
    uv run python scripts/braze_automation/add_two_image_rows_memorial_day.py
    uv run python scripts/braze_automation/add_two_image_rows_memorial_day.py --no-headless
    uv run python scripts/braze_automation/add_two_image_rows_memorial_day.py --dry-run
"""

import argparse
import asyncio
import io
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session
from build_designed_campaign import upload_to_media_library, _close_dnd_editor
from build_pt_campaign import save_as_draft

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────
CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns/"
    "6a028cd67634da008588174e/664223fb71bcf3005760dfc2"
    "?locale=en&campaignName=P_EM_2026_05_15_HAV_PC_D_Memorial_Day_Sale_Reminder&page=1"
)
BRAND = "HAV"
DRIVE_FILE_1 = "1ESIstC-9QVOgpdQUjjZrUHCFVwhKcf_g"  # 1.png → top image
DRIVE_FILE_2 = "1mgv9dDktzxabnPZeYJsE8R1dqCM2AqW7"  # 2.png → second image
# CDN URLs from prior upload (set to skip re-upload)
CACHED_IMG1_CDN = "https://braze-images.com/appboy/communication/assets/image_assets/images/6a029012cfb37800832a056e/original.png"
CACHED_IMG2_CDN = "https://braze-images.com/appboy/communication/assets/image_assets/images/6a029020be22820083ec84b7/original.png"
LINK_IMAGE_1 = "https://havenly.com/"
LINK_IMAGE_2 = "https://havenly.com/#packages-section"

DEBUG_DIR = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _screenshot(page: Page, label: str) -> None:
    try:
        path = DEBUG_DIR / f"debug_md2slices_{label}_{_ts()}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot: {path.name}")
    except Exception as e:
        logger.debug(f"Screenshot failed ({label}): {e}")


def download_drive_file(file_id: str, dest_path: str) -> str:
    """Download a Google Drive file by ID to dest_path using OAuth creds from .env."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    creds = Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN"),
        client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    request = service.files().get_media(fileId=file_id)
    buf = io.FileIO(dest_path, mode="wb")
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.close()
    logger.info(f"Downloaded Drive:{file_id} → {dest_path}")
    return dest_path


async def _get_bee_frame(page: Page):
    for frame in page.frames:
        if "getbee.io" in frame.url:
            logger.info(f"BEE frame: {frame.url[:80]}")
            return frame
    return None


async def _open_dnd_editor(page: Page) -> bool:
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
                return True
        except Exception:
            continue
    logger.warning("'Edit message' button not found")
    return False


async def _drag_image_block_to_top(bee_frame, page: Page) -> bool:
    """Drag the Image content block from the CONTENT sidebar to the top of the canvas."""
    source_el = None
    source_box = None
    for sel in [
        '[aria-label="Image"][class*="sidebar-draggable"]',
        '[aria-label="Image"].sidebar-draggable--cs',
        '[class*="sidebar-draggable"][aria-label="Image"]',
        '[class*="SidebarDraggable"][aria-label="Image"]',
    ]:
        try:
            el = bee_frame.locator(sel)
            if await el.count() > 0:
                box = await el.first.bounding_box()
                if box:
                    source_el = el.first
                    source_box = box
                    logger.info(f"Image draggable: {sel!r} @ {box}")
                    break
        except Exception as e:
            logger.debug(f"Source {sel!r}: {e}")

    if source_box is None:
        logger.error("Image draggable not found in CONTENT sidebar")
        return False

    target_box = None
    for sel in ["[aria-label*='row 1 out of']", "[class*='row-container-outer--first']"]:
        try:
            el = bee_frame.locator(sel)
            if await el.count() > 0:
                box = await el.first.bounding_box()
                if box:
                    target_box = box
                    break
        except Exception:
            continue

    if target_box is None:
        logger.error("First row not found for drop target")
        return False

    src_x = source_box["x"] + source_box["width"] / 2
    src_y = source_box["y"] + source_box["height"] / 2
    drop_x = target_box["x"] + target_box["width"] / 2
    drop_y = target_box["y"] + 8

    logger.info(f"Drag ({src_x:.0f},{src_y:.0f}) → ({drop_x:.0f},{drop_y:.0f})")
    try:
        await page.mouse.move(src_x, src_y)
        await page.wait_for_timeout(300)
        await page.mouse.down()
        await page.wait_for_timeout(300)
        steps = 20
        for i in range(1, steps + 1):
            await page.mouse.move(
                src_x + (drop_x - src_x) * i / steps,
                src_y + (drop_y - src_y) * i / steps,
            )
            await page.wait_for_timeout(40)
        await page.wait_for_timeout(800)
        await page.mouse.up()
        await page.wait_for_timeout(2500)
        logger.info("Drag complete")
        return True
    except Exception as e:
        logger.error(f"Drag failed: {e}")
        return False


async def _set_image_src_and_link(bee_frame, page: Page, src_url: str, link_url: str) -> bool:
    """Set text[0]=src and text[2]=link on the currently-selected image block."""
    # Re-acquire bee_frame in case it changed
    bee_frame = None
    for frame in page.frames:
        if "getbee.io" in frame.url:
            bee_frame = frame
            break
    if bee_frame is None:
        logger.error("BEE frame gone")
        return False

    await page.wait_for_timeout(1000)

    try:
        all_text = bee_frame.locator("input[type='text']")
        count = await all_text.count()
        logger.info(f"Inputs in properties panel: {count}")
        for i in range(min(count, 5)):
            v = await all_text.nth(i).input_value()
            logger.info(f"  text[{i}] = {v[:80]!r}")
    except Exception as e:
        logger.debug(f"Input dump failed: {e}")

    src_set = False
    link_set = False

    try:
        all_text = bee_frame.locator("input[type='text']")
        count = await all_text.count()

        # text[0] = image src URL
        if count >= 1:
            inp = all_text.nth(0)
            await inp.click()
            await inp.fill(src_url)
            await inp.press("Tab")
            await page.wait_for_timeout(500)
            src_set = True
            logger.info(f"Src set → {src_url[:70]}")

        # text[2] = Image link URL (ACTION section)
        if count >= 3:
            inp = all_text.nth(2)
            await inp.click()
            await inp.fill(link_url)
            await inp.press("Tab")
            await page.wait_for_timeout(500)
            link_set = True
            logger.info(f"Link set → {link_url}")

    except Exception as e:
        logger.error(f"_set_image_src_and_link failed: {e}")

    return src_set and link_set


async def _click_image_by_index(bee_frame, page: Page, index: int) -> bool:
    """Click the Nth <img> element in the BEE canvas (0-indexed, top→bottom)."""
    if bee_frame is None:
        return False
    # Neutral click to deselect first
    try:
        await bee_frame.evaluate("() => { document.body.click(); }")
        await page.wait_for_timeout(600)
    except Exception:
        pass

    try:
        imgs = bee_frame.locator("img")
        count = await imgs.count()
        logger.info(f"BEE images: {count}")
        if count > index:
            await imgs.nth(index).scroll_into_view_if_needed()
            await imgs.nth(index).click()
            await page.wait_for_timeout(1500)
            logger.info(f"Clicked img[{index}]")
            return True
    except Exception as e:
        logger.error(f"Click img[{index}] failed: {e}")
    return False


# ── main flow ─────────────────────────────────────────────────────────────────
async def run(headless: bool = True, dry_run: bool = False) -> bool:
    # Step 1: Download both images from Google Drive
    logger.info("Downloading images from Google Drive...")
    tmp1 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp1.close()
    tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp2.close()
    img1_path = download_drive_file(DRIVE_FILE_1, tmp1.name)
    img2_path = download_drive_file(DRIVE_FILE_2, tmp2.name)

    if dry_run:
        logger.info(f"DRY RUN — downloaded to {img1_path} and {img2_path}")
        return True

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await create_context_with_session(browser)
        page = await context.new_page()

        try:
            # Step 2: Use pre-uploaded CDN URLs (images already uploaded)
            img1_cdn = CACHED_IMG1_CDN
            img2_cdn = CACHED_IMG2_CDN
            logger.info(f"img1 CDN: {img1_cdn}")
            logger.info(f"img2 CDN: {img2_cdn}")

            # Step 3: Navigate to the draft campaign
            logger.info("Navigating to draft campaign...")
            await page.goto(CAMPAIGN_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            await _screenshot(page, "00_loaded")

            # Navigate to Compose step (page may land on Schedule)
            for compose_sel in [
                page.get_by_role("link", name="Compose"),
                page.locator("a:has-text('Compose')"),
                page.locator("[data-step='compose']"),
                page.locator("button:has-text('Compose')"),
            ]:
                try:
                    if await compose_sel.count() > 0 and await compose_sel.first.is_visible():
                        await compose_sel.first.click()
                        await page.wait_for_timeout(3000)
                        logger.info("Clicked Compose step")
                        break
                except Exception:
                    continue
            await _screenshot(page, "00b_compose_step")

            # Step 4: Open DnD editor
            logger.info("Opening DnD editor...")
            await _open_dnd_editor(page)
            await page.wait_for_timeout(3000)
            await _screenshot(page, "01_editor_open")

            bee_frame = await _get_bee_frame(page)
            if bee_frame is None:
                logger.error("BEE frame not found")
                return False

            # Step 5: Drag Image block from CONTENT sidebar to top
            logger.info("Dragging new image block to top of canvas...")
            dragged = await _drag_image_block_to_top(bee_frame, page)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "02_after_drag")

            if not dragged:
                logger.error("Drag failed")
                await _screenshot(page, "error_drag")
                return False

            # Step 6: Click the new empty top block to open its properties
            bee_frame = await _get_bee_frame(page)
            try:
                first_row = bee_frame.locator("[aria-label*='row 1 out of']")
                if await first_row.count() == 0:
                    first_row = bee_frame.locator("[class*='row-container-outer']:first-of-type")
                box = await first_row.first.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    await page.mouse.click(cx, cy)
                    await page.wait_for_timeout(2000)
                    logger.info(f"Clicked new top row at ({cx:.0f},{cy:.0f})")
            except Exception as e:
                logger.debug(f"Top row click failed: {e}")
            await _screenshot(page, "03_top_row_selected")

            # Step 7: Set img1 src + link (homepage)
            logger.info("Setting image 1 src and link...")
            ok1 = await _set_image_src_and_link(bee_frame, page, img1_cdn, LINK_IMAGE_1)
            await page.wait_for_timeout(1000)
            await _screenshot(page, "04_img1_set")

            if not ok1:
                logger.warning("Image 1 src/link set may have failed — continuing")

            # Step 8: Click the original (now 2nd) image → set src + link
            logger.info("Clicking original image (now 2nd row)...")
            bee_frame = await _get_bee_frame(page)
            clicked2 = await _click_image_by_index(bee_frame, page, index=1)
            await page.wait_for_timeout(1000)
            await _screenshot(page, "05_img2_selected")

            if not clicked2:
                logger.warning("Could not click 2nd image — attempting by row position")
                try:
                    rows = bee_frame.locator("[aria-label*='row 2 out of'], [aria-label*='row 2 ']")
                    if await rows.count() > 0:
                        box = await rows.first.bounding_box()
                        if box:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                            await page.wait_for_timeout(1500)
                            clicked2 = True
                except Exception:
                    pass

            logger.info("Setting image 2 src and link...")
            ok2 = await _set_image_src_and_link(bee_frame, page, img2_cdn, LINK_IMAGE_2)
            await page.wait_for_timeout(1000)
            await _screenshot(page, "06_img2_set")

            if not ok2:
                logger.warning("Image 2 src/link set may have failed — continuing")

            # Step 9: Close editor
            logger.info("Closing DnD editor...")
            await _close_dnd_editor(page)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "07_editor_closed")

            # Step 10: Save draft
            logger.info("Saving as draft...")
            saved = await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "08_saved")

            logger.info(f"Complete — ok1={ok1}, ok2={ok2}, saved={saved}")
            return saved

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await _screenshot(page, "error")
            return False
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-headless", dest="headless", action="store_false", default=True,
        help="Show browser window"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Download Drive images only, no browser"
    )
    args = parser.parse_args()
    success = asyncio.run(run(headless=args.headless, dry_run=args.dry_run))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

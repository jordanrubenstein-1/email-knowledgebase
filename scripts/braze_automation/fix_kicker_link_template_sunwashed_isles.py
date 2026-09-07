#!/usr/bin/env python3
"""Fix: check unchecked kicker link template checkbox in CZ Sunwashed Isles campaign."""
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
from build_pt_campaign import save_as_draft, _configure_link_templates, load_brand_config, get_brand_entry
from build_push_campaign import wait_for_campaign_editor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND        = "CZ"
CAMPAIGN_ID  = "6a15e91fc48f410081a7b816"
WORKSPACE_ID = "666672a4d8965b005ac6c1bd"
SCRIPT_DIR   = Path(__file__).parent


async def take_debug(page, name):
    try:
        await page.screenshot(path=str(SCRIPT_DIR / f"debug_fix_kicker_{name}.png"), full_page=False)
        logger.info(f"Screenshot: debug_fix_kicker_{name}.png")
    except Exception:
        pass


async def main() -> None:
    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
        logger.info(f"Navigating to campaign: {campaign_url}")
        await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await take_debug(page, "01_after_nav")

        # Click Edit Draft if present
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
            logger.warning(f"wait_for_campaign_editor: {e}")

        # Navigate to Compose step
        for compose_name in ["Compose Messages", "Compose"]:
            try:
                btn = page.get_by_role("button", name=compose_name)
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    logger.info(f"Clicked '{compose_name}'")
                    break
            except Exception:
                continue

        await take_debug(page, "02_compose")

        # Open the email editor
        opened = False
        for sel_name in ["Edit message", "Edit Message", "Edit"]:
            for sel in [
                page.get_by_role("button", name=sel_name),
                page.locator(f"button:has-text('{sel_name}')"),
            ]:
                try:
                    if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                        await sel.first.click()
                        await page.wait_for_timeout(4000)
                        logger.info(f"Clicked '{sel_name}'")
                        opened = True
                        break
                except Exception:
                    continue
            if opened:
                break

        if not opened:
            logger.error("Could not open editor")
            await context.close()
            await browser.close()
            return

        await take_debug(page, "03_editor_open")

        # Apply link templates — now includes final pass for unchecked rows (kicker)
        await _configure_link_templates(page, utm_templates)
        await take_debug(page, "04_after_link_templates")

        # Close editor via Done
        for done_sel in [
            page.get_by_role("button", name="Done", exact=True),
            page.locator("button:has-text('Done')").last,
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                    await done_sel.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Editor modal closed via Done")
                    break
            except Exception:
                continue

        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)
        await take_debug(page, "05_saved")
        logger.info("Done — kicker link template checkbox fixed and draft saved.")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

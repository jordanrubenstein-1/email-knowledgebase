#!/usr/bin/env python3
"""Re-inject updated HTML into the CZ Archive Sale campaign (after HTML edits)."""
import asyncio, json, logging, sys
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import save_as_draft, get_campaign_url_from_page, _configure_link_templates, load_brand_config, get_brand_entry
from build_push_campaign import wait_for_campaign_editor
from create_campaign import fill_html_content

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND        = "CZ"
CAMPAIGN_ID  = "6a121a092e845c0081cb8707"
WORKSPACE_ID = "666672a4d8965b005ac6c1bd"
HTML_FILE    = PROJECT_ROOT / "campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html"
SCRIPT_DIR   = Path(__file__).parent


async def take_debug(page, name):
    try:
        path = str(SCRIPT_DIR / f"debug_reinject_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info(f"Screenshot: {path}")
    except Exception:
        pass


async def main():
    html_body = HTML_FILE.read_text(encoding="utf-8")
    logger.info(f"HTML loaded: {len(html_body)} chars")

    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"]
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        # Navigate directly to campaign
        campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
        logger.info(f"Navigating to campaign: {campaign_url}")
        await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await take_debug(page, "01_after_nav")
        logger.info(f"URL after nav: {page.url}")

        # Check if we're on the overview page (has "Edit Draft") or already in editor
        edit_draft_found = False
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
                    edit_draft_found = True
                    break
            except Exception:
                continue

        if not edit_draft_found:
            logger.info("No 'Edit Draft' button found — may already be in editor")

        await take_debug(page, "02_after_edit_draft")
        logger.info(f"URL after edit draft: {page.url}")

        # Wait for campaign editor to load
        try:
            await wait_for_campaign_editor(page)
            logger.info("Campaign editor loaded")
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

        await take_debug(page, "03_compose_step")
        logger.info(f"URL on compose: {page.url}")

        # Log all visible buttons to diagnose what's on the page
        btn_texts = await page.evaluate("""() => {
            return [...document.querySelectorAll('button, a[role="button"]')]
                .filter(el => el.offsetParent !== null)
                .map(el => el.textContent.trim().substring(0, 40))
                .filter(t => t.length > 0);
        }""")
        logger.info(f"Visible buttons: {btn_texts[:30]}")

        # Open HTML editor via "Edit message" button
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
                        logger.info(f"Clicked '{sel_name}' — editor should be open")
                        opened = True
                        break
                except Exception:
                    continue
            if opened:
                break

        await take_debug(page, "04_editor_open")

        if not opened:
            logger.error("Could not open editor — check debug screenshots")
            await context.close()
            await browser.close()
            return

        # Verify we're in the HTML/CSS Monaco editor (not BEE)
        monaco_count = await page.locator(".monaco-editor").count()
        bee_count = len([f for f in page.frames if "getbee.io" in f.url])
        logger.info(f"Monaco editors: {monaco_count}, BEE frames: {bee_count}")

        if bee_count > 0 and monaco_count == 0:
            logger.error("BEE editor opened — this is a DnD campaign, not HTML/CSS. Aborting.")
            await context.close()
            await browser.close()
            return

        # Inject updated HTML
        await fill_html_content(page, html_body)
        logger.info("HTML injected")

        await take_debug(page, "05_html_injected")

        # Apply UTM templates
        await _configure_link_templates(page, utm_templates)

        # Close editor
        for done_sel in [
            page.get_by_role("button", name="Done", exact=True),
            page.locator("button:has-text('Done')").last,
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                    await done_sel.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Editor closed via Done")
                    break
            except Exception:
                continue

        # Save as draft
        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)
        braze_url = get_campaign_url_from_page(page.url) or page.url
        logger.info(f"Saved. URL: {braze_url}")

        await take_debug(page, "06_final")

        await context.close()
        await browser.close()

    print(f"\nDone. Campaign: {braze_url}")


if __name__ == "__main__":
    asyncio.run(main())

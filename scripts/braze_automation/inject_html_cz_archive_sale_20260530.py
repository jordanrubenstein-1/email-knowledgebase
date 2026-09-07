#!/usr/bin/env python3
"""
Inject pre-built HTML into the CZ Archive Sale Braze campaign.

The campaign shell (name, subject, preheader, audience, delivery, conversions)
is already configured. This script opens the Compose step HTML editor and
replaces the body with our pre-built HTML (which has all 12 Braze CDN image URLs).
UTM link templates are applied in the same editor session before closing.

Campaign name: P_EM_2026_05_30_CZ_D_Archive_Sale
HTML file:     campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session
from build_pt_campaign import (
    save_as_draft,
    get_campaign_url_from_page,
    _configure_link_templates,
    load_brand_config,
    get_brand_entry,
)
from build_push_campaign import navigate_to_campaigns_list, _set_status_filter, wait_for_campaign_editor
from build_designed_campaign import _search_with_enter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BRAND         = "CZ"
CAMPAIGN_NAME = "P_EM_2026_05_30_CZ_D_Archive_Sale"
HTML_FILE     = PROJECT_ROOT / "campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html"


async def inject_html(page, html_body: str) -> bool:
    """Inject HTML into the Monaco editor inside the email editor modal."""
    html_json = json.dumps(html_body)

    # Click Content tab (avoid the sidebar nav button)
    content_tab = page.locator("button[aria-label='Content']:not([data-route])")
    if await content_tab.count() == 0:
        content_tab = page.get_by_label("Content").nth(1)
    try:
        await content_tab.click(timeout=5000)
        await page.wait_for_timeout(500)
        logger.info("Clicked Content tab")
    except Exception as e:
        logger.warning(f"Content tab click failed: {e} — proceeding anyway")

    # Strategy 1: Monaco JS API
    monaco_editor = page.locator(".monaco-editor")
    if await monaco_editor.count() > 0:
        result = await page.evaluate(f"""
            (() => {{
                const content = {html_json};
                try {{
                    const editors = window.monaco?.editor?.getEditors?.();
                    if (editors && editors.length > 0) {{
                        editors[0].setValue(content);
                        return {{ success: true, method: 'getEditors' }};
                    }}
                }} catch (e) {{}}
                try {{
                    const models = window.monaco?.editor?.getModels?.();
                    if (models && models.length > 0) {{
                        models[0].setValue(content);
                        return {{ success: true, method: 'getModels' }};
                    }}
                }} catch (e) {{}}
                return {{ success: false }};
            }})()
        """)
        if result.get("success"):
            logger.info(f"HTML injected via Monaco API ({result['method']})")
            return True

        # Strategy 2: Clipboard paste
        logger.info("Monaco API failed — trying clipboard paste")
        try:
            await page.evaluate(f"navigator.clipboard.writeText({html_json})")
            await monaco_editor.first.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+a")
            await page.wait_for_timeout(100)
            await page.keyboard.press("Meta+v")
            await page.wait_for_timeout(500)
            logger.info("HTML injected via clipboard paste")
            return True
        except Exception as e:
            logger.warning(f"Clipboard paste failed: {e}")

    # Strategy 3: Textarea fallback
    editor = page.get_by_role("textbox", name="Editor content;Press Alt+F1")
    if await editor.count() > 0:
        await editor.fill(html_body, timeout=15000)
        logger.info("HTML injected via editor fill()")
        return True

    textarea = page.locator("textarea")
    if await textarea.count() > 0:
        await textarea.first.fill(html_body)
        logger.info("HTML injected via textarea fill()")
        return True

    logger.error("Could not find any HTML editor element")
    return False


async def main():
    html_body = HTML_FILE.read_text(encoding="utf-8")
    logger.info(f"HTML file loaded: {len(html_body)} chars from {HTML_FILE.name}")

    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        from login import ensure_logged_in, select_workspace
        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        # Navigate directly to campaign by ID (avoids flaky search box timing)
        CAMPAIGN_ID = "6a1215efb7c1340083bd6611"
        WORKSPACE_ID = "666672a4d8965b005ac6c1bd"
        campaign_edit_url = (
            f"https://dashboard-07.braze.com/engagement/campaigns"
            f"/{CAMPAIGN_ID}/{WORKSPACE_ID}"
        )
        logger.info(f"Navigating to campaign: {campaign_edit_url}")
        await page.goto(campaign_edit_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Look for "Edit Draft" button on overview page
        for edit_sel in [
            page.get_by_role("button", name="Edit Draft"),
            page.get_by_role("link", name="Edit Draft"),
            page.get_by_role("button", name="Edit"),
            page.locator("a:has-text('Edit Draft')"),
            page.locator("button:has-text('Edit Draft')"),
        ]:
            try:
                if await edit_sel.count() > 0 and await edit_sel.first.is_visible(timeout=3000):
                    await edit_sel.first.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Clicked Edit Draft button")
                    break
            except Exception:
                continue

        await wait_for_campaign_editor(page)
        logger.info(f"Campaign editor loaded. URL: {page.url}")

        # Make sure we're on Compose step
        try:
            compose_btn = page.get_by_role("button", name="Compose Messages")
            if await compose_btn.count() == 0:
                compose_btn = page.get_by_role("button", name="Compose")
            if await compose_btn.count() > 0:
                await compose_btn.click()
                await page.wait_for_timeout(1500)
                logger.info("Navigated to Compose step")
        except Exception as e:
            logger.warning(f"Could not click Compose step: {e}")

        # Take screenshot of compose step to see current state
        try:
            dbg = str(Path(__file__).parent / "debug_compose_before_inject.png")
            await page.screenshot(path=dbg, full_page=False)
            logger.info(f"Compose screenshot: {dbg}")
        except Exception:
            pass

        # Click "Edit message" to open the HTML editor modal
        logger.info("Opening HTML editor via 'Edit message'...")
        opened = False
        for sel in [
            page.get_by_role("button", name="Edit message"),
            page.locator("button:has-text('Edit message')"),
            page.get_by_role("button", name="Edit Message"),
        ]:
            try:
                if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                    await sel.first.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Clicked 'Edit message'")
                    opened = True
                    break
            except Exception:
                continue

        if not opened:
            # For HTML/CSS campaigns the editor might open automatically or via a different button
            logger.warning("'Edit message' not found — checking for editor modal already open")

        # Screenshot to see editor state
        try:
            dbg2 = str(Path(__file__).parent / "debug_editor_open.png")
            await page.screenshot(path=dbg2, full_page=False)
            logger.info(f"Editor state screenshot: {dbg2}")
        except Exception:
            pass

        # Inject HTML
        logger.info("Injecting HTML...")
        ok = await inject_html(page, html_body)
        if not ok:
            logger.error("HTML injection failed — check debug screenshots")
        else:
            logger.info("HTML injection succeeded")

        # Apply UTM templates (while still in editor modal)
        logger.info("Applying UTM link templates...")
        await _configure_link_templates(page, utm_templates)

        # Close editor modal via Done
        logger.info("Closing editor modal...")
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

        # Save as draft
        logger.info("Saving as draft...")
        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)

        braze_url = get_campaign_url_from_page(page.url) or page.url
        logger.info(f"Saved. URL: {braze_url}")

        try:
            final = str(Path(__file__).parent / "debug_inject_final.png")
            await page.screenshot(path=final, full_page=False)
            logger.info(f"Final screenshot: {final}")
        except Exception:
            pass

        await context.close()
        await browser.close()

    print(f"\nHTML injected and saved. Braze URL: {braze_url}")


if __name__ == "__main__":
    asyncio.run(main())

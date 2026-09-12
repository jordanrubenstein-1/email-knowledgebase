#!/usr/bin/env python3
"""Fix wrong alt texts in P_EM_2026_06_09_CZ_D_Style_Guide_Entryway_Styling.

Current HTML has:
  img 1 (hero):       alt="The Citizenry logo"   → should be "The Entryway Edit"
  imgs 2–6 (products/CTA): alt="Shop All Decor Link: https://..."
                         → should be product names + CTA text

This script patches the alt attributes in-memory (CDN URLs are unchanged) and
re-injects the fixed HTML into the Braze campaign editor.
"""
import asyncio
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace, save_session
from build_pt_campaign import _configure_link_templates, load_brand_config, get_brand_entry, save_as_draft
from create_campaign import fill_html_content

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND        = "CZ"
CAMPAIGN_ID  = "6a15f20f1146410081a36fb8"
WORKSPACE_ID = "666672a4d8965b005ac6c1bd"
SCRIPT_DIR   = Path(__file__).parent

# ---------------------------------------------------------------------------
# Current HTML fetched from Braze API — alt texts patched below
# ---------------------------------------------------------------------------
_CURRENT_HTML = """\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <!--[if !mso]><!-->
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <!--<![endif]-->
  <title></title>
  <!--[if mso]>
  <noscript>
    <xml><o:OfficeDocumentSettings>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml>
  </noscript>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#ffffff;">
    <tr>
      <td align="center" style="padding:0;">
        <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;">
          <!-- Slice 1: 1.png — The Entryway Edit -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-decor?lid=7zg0hwlr2xya" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe2af4f4ff11629350c7/original.png?1779826217" width="600" alt="The Entryway Edit" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 2: 2.png — Elora Jute Accent Rug | 3.png — Hinoki Wood Mirror — 50/50 -->
<tr><td style="padding:0;line-height:0;font-size:0;">
  <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0"><tr><td width="300" valign="top"><![endif]-->
  <div style="display:inline-block;width:50%;max-width:300px;vertical-align:top;">
    <a href="https://www.the-citizenry.com/products/elora-jute-accent-rug?v=46202238140603&lid=2f4hk6hlomvs" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe2cb2657400898df2c3/original.png?1779826220" width="300" alt="Elora Jute Accent Rug" style="display:block;width:100%;height:auto;border:0;"></a>
  </div>
  <!--[if mso]></td><td width="300" valign="top"><![endif]-->
  <div style="display:inline-block;width:50%;max-width:300px;vertical-align:top;">
    <a href="https://www.the-citizenry.com/products/hinoki-wood-mirror?lid=j5vaqaqgxnn2" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe31b4a8b40dde037500/original.png?1779826224" width="300" alt="Hinoki Wood Mirror" style="display:block;width:100%;height:auto;border:0;"></a>
  </div>
  <!--[if mso]></td></tr></table><![endif]-->
</td></tr>
          <!-- Slice 3: 4.png — Merapi Storage Baskets | 5.png — Azad Leather Tray — 50/50 -->
<tr><td style="padding:0;line-height:0;font-size:0;">
  <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0"><tr><td width="300" valign="top"><![endif]-->
  <div style="display:inline-block;width:50%;max-width:300px;vertical-align:top;">
    <a href="https://www.the-citizenry.com/products/merapi-storage-baskets?lid=9d8lqnn7nali" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe33ec3de661d9cafc1e/original.png?1779826226" width="300" alt="Merapi Storage Baskets" style="display:block;width:100%;height:auto;border:0;"></a>
  </div>
  <!--[if mso]></td><td width="300" valign="top"><![endif]-->
  <div style="display:inline-block;width:50%;max-width:300px;vertical-align:top;">
    <a href="https://www.the-citizenry.com/products/azad-leather-tray?lid=ekvqqcqqcmxy" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe354880978d7ee57155/original.png?1779826228" width="300" alt="Azad Leather Tray" style="display:block;width:100%;height:auto;border:0;"></a>
  </div>
  <!--[if mso]></td></tr></table><![endif]-->
</td></tr>
          <!-- Slice 4: 6.png — Shop All Decor -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-decor?lid=jguqzsbpzc87" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a15fe37b9146ed4819c9d4a/original.png?1779826230" width="600" alt="Shop All Decor" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Kicker: ymal -->
<tr><td style="padding:0;">
{{content_blocks.${product_recs} | id: 'cb13'}}
</td></tr>
          <!-- Footer: content blocks + disclaimer -->
<tr><td style="padding:0;">
{{content_blocks.${CZ_Main_Footer} | id: 'cb14'}}
{{content_blocks.${Havenly_Footer_1} | id: 'cb15'}}
{{content_blocks.${Havenly_Footer_2} | id: 'cb16'}}
{{content_blocks.${Havenly_Footer_3} | id: 'cb11'}}
{{content_blocks.${unsub_block} | id: 'cb17'}}
</td></tr>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


async def take_debug(page, name: str) -> None:
    try:
        path = str(SCRIPT_DIR / f"debug_fix_alts_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info(f"Screenshot: {path}")
    except Exception:
        pass


async def main() -> None:
    html = _CURRENT_HTML
    logger.info(f"Fixed HTML ready: {len(html)} chars")

    global_config = load_brand_config()
    brand_entry   = get_brand_entry(BRAND, global_config)
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
        await save_session(context)
        await select_workspace(page, BRAND)

        # Navigate directly to the campaign compose step
        campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
        logger.info(f"Navigating to: {campaign_url}")
        await page.goto(campaign_url, wait_until="load", timeout=30000)

        # Wait for campaign content to fully render (spinner disappears, compose content appears)
        logger.info("Waiting for campaign page to render...")
        try:
            await page.wait_for_selector(
                "button:has-text('Edit message'), a:has-text('Edit message'), "
                "[role='tab']:has-text('Variant'), button:has-text('Preview and test')",
                timeout=30000,
            )
        except Exception:
            logger.warning("Timed out waiting for compose content — continuing anyway")
        await page.wait_for_timeout(2000)
        await take_debug(page, "01_campaign_loaded")

        # Click Variant 1 if it's not already selected
        for sel in [
            page.get_by_role("tab", name="Variant 1"),
            page.locator("[role='tab']:has-text('Variant 1')"),
            page.get_by_text("Variant 1", exact=True),
        ]:
            try:
                if await sel.count() > 0 and await sel.first.is_visible(timeout=2000):
                    await sel.first.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Clicked Variant 1")
                    break
            except Exception:
                continue

        # Scroll to expose the email preview and "Edit message" button
        await page.evaluate("window.scrollBy(0, 1500)")
        await page.wait_for_timeout(1000)
        await take_debug(page, "02_scrolled")

        # Open the HTML editor modal
        opened_modal = False
        for btn_sel in [
            page.get_by_role("button", name="Edit message"),
            page.locator("button:has-text('Edit message')"),
            page.get_by_role("link", name="Edit message"),
            page.locator("a:has-text('Edit message')"),
        ]:
            try:
                if await btn_sel.count() > 0 and await btn_sel.first.is_visible(timeout=5000):
                    await btn_sel.first.scroll_into_view_if_needed()
                    await btn_sel.first.click()
                    await page.wait_for_timeout(2500)
                    opened_modal = True
                    logger.info("Opened HTML editor modal")
                    break
            except Exception:
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(400)

        if not opened_modal:
            logger.error("Could not open HTML editor modal")
            await take_debug(page, "error_no_modal")
            await context.close()
            await browser.close()
            return

        await take_debug(page, "03_modal_open")

        # Verify Monaco editor is present (not BEE)
        monaco = page.locator(".monaco-editor")
        if await monaco.count() == 0:
            logger.error("Monaco editor not found — may be BEE editor, aborting")
            await take_debug(page, "error_no_monaco")
            await context.close()
            await browser.close()
            return

        # Inject the fixed HTML
        logger.info("Injecting fixed HTML...")
        success = await fill_html_content(page, html)
        if not success:
            logger.error("fill_html_content returned False")
        await take_debug(page, "04_html_injected")

        # Re-apply UTM link template (benign if already applied)
        logger.info("Applying link template...")
        try:
            await _configure_link_templates(page, utm_templates)
        except Exception as e:
            logger.warning(f"Link template step: {e} (non-fatal if already applied)")
        await take_debug(page, "05_link_template")

        # Click Done to close the modal
        for done_sel in [
            page.get_by_role("button", name="Done"),
            page.locator("button:has-text('Done')"),
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.first.is_visible(timeout=5000):
                    await done_sel.first.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Clicked Done")
                    break
            except Exception:
                continue
        await take_debug(page, "06_done_clicked")

        # Save as draft
        saved = await save_as_draft(page, dry_run=False)
        await take_debug(page, "07_saved")
        if saved:
            logger.info("✅  Campaign saved — alt texts fixed")
        else:
            logger.warning("⚠️  save_as_draft returned False — verify manually")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

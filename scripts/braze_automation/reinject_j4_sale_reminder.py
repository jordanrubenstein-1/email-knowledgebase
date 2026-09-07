#!/usr/bin/env python3
"""Re-inject corrected HTML into P_EM_2026_07_04_CZ_D_Fourth_Of_July_Sale_Reminder.

Fixes: alt text on slices 2-7 was "Shop 25% Off" / Link:... instead of category names.
Links are already correct; only alt attributes need fixing.
"""
import asyncio, logging, sys
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import save_as_draft, _configure_link_templates, load_brand_config, get_brand_entry
from create_campaign import fill_html_content

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND        = "CZ"
CAMPAIGN_ID  = "6a3eb4635ef896008543062c"
WORKSPACE_ID = "666672a4d8965b005ac6c1bd"
SCRIPT_DIR   = Path(__file__).parent

CORRECTED_HTML = """\
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
          <!-- Slice 1: 1.png — The Citizenry logo -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/all-best-sellers?lid=nws6wuqa1jju" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb448f5ccd90081000a47/original.png?1782494279" width="600" alt="The Citizenry logo" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 2: 2.png — Rugs -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-rugs-1?lid=457spyxsheq8" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb44a294b95007fcb2f18/original.png?1782494281" width="600" alt="Rugs" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 3: 3.png — Bedding -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-bedding-2?lid=bxicnkur1f1k" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb44d5a0f6b007e2f29ab/original.png?1782494284" width="600" alt="Bedding" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 4: 4.png — Handcrafted Furniture -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-furniture?lid=u0qbd91zlptw" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb44e2d2d20655312c45d/original.png?1782494285" width="600" alt="Handcrafted Furniture" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 5: 5.png — Pillows -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-pillows?lid=xvux6k81nyt3" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb451c966ab008355f664/original.png?1782494288" width="600" alt="Pillows" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 6: 6.png — Accents -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/shop-all-decor?lid=p45nzjdwdkim" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb4532d2d20008312fa1b/original.png?1782494290" width="600" alt="Accents" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Slice 7: 7.png — Archive Sale -->
<tr><td style="padding:0;line-height:0;"><a href="https://www.the-citizenry.com/collections/archive-sale?lid=28luu61ye7pl" style="display:block;" target="_blank"><img src="https://braze-images.com/appboy/communication/assets/image_assets/images/6a3eb4553156b10081a89999/original.png?1782494293" width="600" alt="Archive Sale" style="display:block;width:100%;height:auto;border:0;"></a></td></tr>
          <!-- Footer: content blocks + disclaimer -->
<tr><td style="padding:0;">
{{content_blocks.${CZ_Main_Footer} | id: 'cb1'}}
{{content_blocks.${Havenly_Footer_1} | id: 'cb2'}}
{{content_blocks.${Havenly_Footer_2} | id: 'cb3'}}
{{content_blocks.${Havenly_Footer_3} | id: 'cb4'}}
<p style="color:#9D9D9D;font-size:11px;font-style:italic;text-align:center;margin:8px 0 0 0;">Offers and pricing are subject to change, see site for details.</p>
{{content_blocks.${unsub_block} | id: 'cb5'}}
</td></tr>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


async def take_debug(page, name):
    try:
        path = str(SCRIPT_DIR / f"reinject_j4_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info(f"Screenshot: {path}")
    except Exception:
        pass


async def main():
    logger.info(f"HTML prepared: {len(CORRECTED_HTML)} chars")

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

        campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
        logger.info(f"Navigating to: {campaign_url}")
        await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await take_debug(page, "01_after_nav")

        # Click "Edit Draft" if present
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
                pass

        # Click "Compose Messages" wizard step
        for sel in ["text=Compose Messages", "text=Compose Message", "[data-step='compose']"]:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=3000):
                    await loc.first.click()
                    await page.wait_for_timeout(3000)
                    logger.info(f"Clicked compose step via: {sel}")
                    break
            except Exception:
                pass
        await take_debug(page, "02_compose_step")

        # Click "Edit message"
        edit_msg = page.get_by_role("button", name="Edit message")
        if await edit_msg.count() == 0:
            edit_msg = page.locator("button:has-text('Edit message')")
        await edit_msg.first.scroll_into_view_if_needed()
        await edit_msg.first.click()
        await page.wait_for_timeout(4000)
        await take_debug(page, "03_edit_message")

        # Verify we're in Monaco (HTML/CSS editor)
        portal = page.locator("#email-message-composer-portal")
        if await portal.count() == 0:
            logger.error("No email-message-composer-portal found — may be DnD editor")
            await take_debug(page, "04_no_portal")
            return

        # Check for HTML tab
        html_tab = portal.locator("button:has-text('HTML'), [role='tab']:has-text('HTML')")
        if await html_tab.count() > 0:
            await html_tab.first.click()
            await page.wait_for_timeout(1000)
            logger.info("Clicked HTML tab")

        logger.info("Injecting corrected HTML...")
        await fill_html_content(page, CORRECTED_HTML)
        await take_debug(page, "05_after_fill")

        # Configure UTM link templates
        logger.info("Configuring link templates...")
        try:
            await _configure_link_templates(page, utm_templates)
        except Exception as e:
            logger.warning(f"Link template step: {e} (benign if already set)")

        # Click Done
        done_btn = page.get_by_role("button", name="Done")
        if await done_btn.count() > 0:
            await done_btn.first.click()
            await page.wait_for_timeout(3000)
            logger.info("Clicked Done")
        await take_debug(page, "06_after_done")

        # Save as draft
        logger.info("Saving as draft...")
        await save_as_draft(page, dry_run=False)
        await take_debug(page, "07_saved")

        logger.info("Re-injection complete. Alt text fixed on slices 2-7.")


if __name__ == "__main__":
    asyncio.run(main())

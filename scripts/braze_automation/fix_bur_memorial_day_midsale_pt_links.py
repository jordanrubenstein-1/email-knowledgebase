#!/usr/bin/env python3
"""
Fix: add Memorial Day Sale link and un-bold signoff on the BUR Mid-Sale Check-In PT draft.

Campaign: P_EM_2026_05_19_BW_PT_Memorial_Day_Sale_Mid_Sale_Check_In_Email
Internal ID: 6a04dffb496635008398b2ee
Workspace:   67093a1f24ebbe0065cb9c77

Changes:
  1. <strong>Memorial Day Sale</strong>  →  linked to https://burrow.com/
  2. <strong>The Burrow Team</strong>    →  plain text (no bold)

Usage:
    uv run python scripts/braze_automation/fix_bur_memorial_day_midsale_pt_links.py
    uv run python scripts/braze_automation/fix_bur_memorial_day_midsale_pt_links.py --no-headless
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session
from build_pt_campaign import save_as_draft

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns/"
    "6a04dffb496635008398b2ee/67093a1f24ebbe0065cb9c77"
)

UPDATED_HTML = """\
<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml"
      xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">
<!--
  BW (Burrow) Plain-Text Email Template v1.0
  Based on production emails: seg_2025_10_07_bw_pt_listadditions_fall_sale,
  p_em_2025_12_09_bw_pt_am_cyber_week_final_hours

  Structure:
    Row 1 — Body content (greeting + body + signoff)
    Row 2 — Disclaimer (optional, sale periods only)
    Row 3 — Unsubscribe

  Placeholder markers for programmatic injection:
    BODY_CONTENT   — replaced with converted body HTML
    SIGNOFF        — replaced with signoff HTML, or default used
    DISCLAIMER     — replaced with disclaimer text, or row removed if empty

  Signoff default: "Warmly," / "The Burrow Team" (bold)
-->
<head>
  <title></title>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">

  <!--[if mso]>
  <xml>
    <w:WordDocument xmlns:w="urn:schemas-microsoft-com:office:word">
      <w:DontUseAdvancedTypographyReadingMail/>
    </w:WordDocument>
    <o:OfficeDocumentSettings>
      <o:PixelsPerInch>96</o:PixelsPerInch>
      <o:AllowPNG/>
    </o:OfficeDocumentSettings>
  </xml>
  <![endif]-->

  <!--[if !mso]><!-->
  <link href="https://d1qnmprc5tnkc9.cloudfront.net/fonts/c506d6b24ddd6d6a415b040bedcc2c5d.woff"
        rel="stylesheet" type="text/css">
  <!--<![endif]-->

  <style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; }
    a[x-apple-data-detectors] {
      color: inherit !important;
      text-decoration: inherit !important;
    }
    #MessageViewBody a {
      color: inherit;
      text-decoration: none;
    }
    p { line-height: inherit; }
    .desktop_hide,
    .desktop_hide table {
      mso-hide: all;
      display: none;
      max-height: 0;
      overflow: hidden;
    }
    .image_block img+div { display: none; }
    sub, sup { font-size: 75%; line-height: 0; }

    @media (max-width: 620px) {
      .mobile_hide {
        display: none;
      }
      .row-content {
        width: 100% !important;
      }
      .stack .column {
        width: 100%;
        display: block;
      }
      .mobile_hide {
        min-height: 0;
        max-height: 0;
        max-width: 0;
        overflow: hidden;
        font-size: 0;
      }
      .desktop_hide,
      .desktop_hide table {
        display: table !important;
        max-height: none !important;
      }
    }
  </style>

  <!--[if mso]>
  <style>
    sup, sub { font-size: 100% !important; }
    sup { mso-text-raise: 10%; }
    sub { mso-text-raise: -10%; }
  </style>
  <![endif]-->
</head>

<body class="body"
      style="margin:0;background-color:#fff;padding:0;-webkit-text-size-adjust:none;text-size-adjust:none;">

<!-- Outer container -->
<table class="nl-container" width="100%" border="0" cellpadding="0"
       cellspacing="0" role="presentation"
       style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;">
<tbody><tr><td>

<!-- ================================================================
     ROW 1: BODY CONTENT (greeting + body + signoff)
     ================================================================ -->
<table class="row row-1" align="center" width="100%" border="0"
       cellpadding="0" cellspacing="0" role="presentation"
       style="mso-table-lspace:0;mso-table-rspace:0;">
<tbody><tr><td>
  <table class="row-content stack" align="center" border="0" cellpadding="0"
         cellspacing="0" role="presentation"
         style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto;"
         width="600">
  <tbody><tr>
    <td class="column column-1" width="100%"
        style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top;">

      <!-- Block 1: Greeting -->
      <table class="paragraph_block block-1" width="100%" border="0"
             cellpadding="10" cellspacing="0" role="presentation"
             style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word;">
      <tr><td class="pad">
        <div style="color:#101b24;direction:ltr;font-family:Arial,Sans-serif;font-size:14px;font-weight:400;letter-spacing:0;line-height:1.5;text-align:left;mso-line-height-alt:21px;">
          <p style="margin:0;">Hi {{${first_name} | default: 'there'}},</p>
        </div>
      </td></tr>
      </table>

      <!-- Block 2: Body content -->
      <table class="paragraph_block block-2" width="100%" border="0"
             cellpadding="10" cellspacing="0" role="presentation"
             style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word;">
      <tr><td class="pad">
        <div style="color:#101b24;direction:ltr;font-family:Arial,Sans-serif;font-size:14px;font-weight:400;letter-spacing:0;line-height:1.5;text-align:left;mso-line-height-alt:21px;">
<p style="margin:0;margin-bottom:0">We know you've been thinking about it. The <a href="https://burrow.com/" style="color: #0000EE; text-decoration: underline;"><strong>Memorial Day Sale</strong></a> is still going, and the bestselling Nomad sofa is <strong>up to 35% off</strong> plus free shipping.</p><p style="margin:0;margin-bottom:0">&nbsp;</p><p style="margin:0">If you've been waiting for a sign, this is it. Save while you still can!</p>
        </div>
      </td></tr>
      </table>

      <!-- Block 3: Signoff -->
      <table class="paragraph_block block-3" width="100%" border="0"
             cellpadding="10" cellspacing="0" role="presentation"
             style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word;">
      <tr><td class="pad">
        <div style="color:#101b24;direction:ltr;font-family:Arial,Sans-serif;font-size:14px;font-weight:400;letter-spacing:0;line-height:1.5;text-align:left;mso-line-height-alt:21px;">
<p style="margin:0;">The Burrow Team</p>
        </div>
      </td></tr>
      </table>

    </td>
  </tr></tbody>
  </table>
</td></tr></tbody>
</table>



<!-- ================================================================
     ROW 3: FOOTER (content block — includes address + unsubscribe)
     ================================================================ -->
{{content_blocks.${PT_unsubscribe} | id: 'cb1'}}

</td></tr></tbody>
</table>
<!-- End -->
</body>
</html>
"""

DEBUG_DIR = Path(__file__).parent


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _screenshot(page, label):
    try:
        path = DEBUG_DIR / f"debug_fix_bur_midsale_{label}_{_ts()}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot: {path.name}")
    except Exception as e:
        logger.debug(f"Screenshot failed: {e}")


async def run(headless: bool = True) -> bool:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()

        try:
            logger.info("Navigating to campaign...")
            await page.goto(CAMPAIGN_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            await _screenshot(page, "01_loaded")

            # Click Compose step (step 2)
            compose_selectors = [
                "button:has-text('Compose Message')",
                "li[data-step='1'] button",
                "button[aria-label='Compose Message']",
                "a:has-text('Compose')",
            ]
            compose_clicked = False
            for sel in compose_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click(timeout=5000)
                        compose_clicked = True
                        logger.info(f"Clicked compose via: {sel}")
                        break
                except Exception:
                    pass

            if not compose_clicked:
                logger.info("Could not click compose explicitly — assuming already on compose")

            await page.wait_for_timeout(3000)
            await _screenshot(page, "02_compose")

            # Click into the message variant to open editor
            # Look for an "Edit" button on the email variant
            for edit_sel in [
                "button:has-text('Edit Message')",
                "button[aria-label*='Edit']",
                "button:has-text('Edit')",
            ]:
                try:
                    el = page.locator(edit_sel).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click(timeout=5000)
                        logger.info(f"Clicked edit via: {edit_sel}")
                        await page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            await _screenshot(page, "03_editor_open")

            # Switch to Content tab
            content_tab = page.locator("button[aria-label='Content']:not([data-route])")
            if await content_tab.count() == 0:
                content_tab = page.get_by_label("Content").nth(1)
            try:
                await content_tab.click(timeout=5000)
                await page.wait_for_timeout(500)
                logger.info("Switched to Content tab")
            except Exception:
                logger.warning("Could not click Content tab — may already be on it")

            await _screenshot(page, "04_content_tab")

            # The updated HTML is known from the REST API — apply fixes directly.
            # We don't need to read from the editor; just set the corrected content.
            updated_html = UPDATED_HTML
            logger.info(f"Setting {len(updated_html)} chars of updated HTML")

            # Wait for editor to be ready
            await page.wait_for_timeout(2000)

            # Try Monaco API first
            html_json = json.dumps(updated_html)
            set_ok = await page.evaluate(f"""
                (() => {{
                    const content = {html_json};
                    try {{
                        const editors = window.monaco?.editor?.getEditors?.();
                        if (editors && editors.length > 0) {{
                            editors[0].setValue(content);
                            return {{ success: true, method: 'getEditors' }};
                        }}
                    }} catch(e) {{}}
                    try {{
                        const models = window.monaco?.editor?.getModels?.();
                        if (models && models.length > 0) {{
                            models[0].setValue(content);
                            return {{ success: true, method: 'getModels' }};
                        }}
                    }} catch(e) {{}}
                    return {{ success: false }};
                }})()
            """)

            if set_ok and set_ok.get("success"):
                logger.info(f"HTML set via Monaco API ({set_ok['method']})")
            else:
                # Clipboard paste fallback
                logger.info("Monaco API unavailable — using clipboard paste")
                await page.evaluate(f"navigator.clipboard.writeText({html_json})")
                editor_area = page.locator(".monaco-editor, [role='textbox'][aria-label*='Editor']").first
                await editor_area.click(timeout=5000)
                await page.wait_for_timeout(200)
                await page.keyboard.press("Meta+a")
                await page.wait_for_timeout(100)
                await page.keyboard.press("Meta+v")
                await page.wait_for_timeout(500)
                logger.info("HTML set via clipboard paste")

            await page.wait_for_timeout(1000)
            await _screenshot(page, "05_html_updated")

            # Close the message editor modal by clicking "Done"
            done_btn = page.get_by_role("button", name="Done", exact=True)
            try:
                await done_btn.wait_for(state="visible", timeout=5000)
                await done_btn.click()
                await page.wait_for_timeout(2000)
                logger.info("Closed message editor modal")
            except Exception:
                logger.warning("Could not find Done button — proceeding anyway")

            await _screenshot(page, "05b_modal_closed")

            # Save as draft
            saved = await save_as_draft(page, dry_run=False)
            if saved:
                logger.info("Saved as draft successfully")
            else:
                logger.warning("save_as_draft returned False — check screenshot")

            await _screenshot(page, "06_saved")
            return saved

        except Exception:
            logger.exception("Unexpected error")
            await _screenshot(page, "ERROR_unexpected")
            return False
        finally:
            await browser.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    ok = await run(headless=not args.no_headless)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())

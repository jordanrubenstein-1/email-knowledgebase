#!/usr/bin/env python3
"""Clear the stray Preheader field on the STF PT Labor Day Event Final Hours PM campaign.

Follow-up fix to edit_pt_stf_labor_day_final_hours_20260831.py: that script
corrected the Subject field and de-duplicated the body greeting, but left the
Preheader field untouched — it was already set to "Final hours for 20% off"
(identical to the subject) from before, a leftover of the same original
auto-build issue. Per CLAUDE.md ("Plain-Text PH: N/A — omit"), PT emails
never carry a preheader, so this clears it to empty and saves as a draft
(no send/schedule).

Campaign: P_EM_2026_09_08_SF_PT_Labor_Day_Event_Final_Hours_PM
Braze:     https://dashboard-07.braze.com/engagement/campaigns/6a95f9e9272048008642557b/666716b3858150005b566956
Asana GID: 1218024407555518
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

BRAND = "STF"
CAMPAIGN_ID = "6a95f9e9272048008642557b"
WORKSPACE_ID = "666716b3858150005b566956"
SCRIPT_DIR = Path(__file__).parent


async def _debug(page, name: str) -> None:
    try:
        path = str(SCRIPT_DIR / f"debug_stf_pt_clearph_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info("Screenshot: %s", path)
    except Exception:
        pass


async def clear_preheader() -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await ensure_logged_in(page)
            await select_workspace(page, BRAND)

            campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
            logger.info("Navigating to campaign: %s", campaign_url)
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

            for compose_name in ["Compose Messages", "Compose"]:
                try:
                    btn = page.get_by_role("button", name=compose_name)
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        logger.info("Clicked '%s'", compose_name)
                        break
                except Exception:
                    continue

            await _debug(page, "02_compose_step")

            # Open the "Edit sending info" panel (static Subject/Preheader
            # display on the compose overview -> editable Monaco fields).
            opened = False
            edit_btn = page.get_by_role("button", name="Edit sending info", exact=False)
            if await edit_btn.count() > 0 and await edit_btn.first.is_visible(timeout=4000):
                await edit_btn.first.click()
                await page.wait_for_timeout(1500)
                opened = True
                logger.info("Clicked 'Edit sending info'")
            if not opened:
                raise RuntimeError("Could not find/click 'Edit sending info' — check debug screenshots")

            await _debug(page, "03_sending_info_open")

            # Locate the Preheader Monaco field specifically by id fragment
            # (mirrors _fill_monaco_field's approach in build_designed_campaign.py,
            # but here we need to detect+clear rather than blind-fill, since an
            # empty string is falsy and that helper skips it entirely).
            textarea = page.locator("[id*='preheader-input']")
            found = await textarea.count() > 0
            logger.info("Preheader Monaco textarea found: %s (count=%d)", found, await textarea.count())
            if not found:
                raise RuntimeError("Could not locate preheader-input field — check debug screenshots")

            await textarea.first.wait_for(state="attached", timeout=4000)
            view_lines = textarea.first.locator(
                "xpath=ancestor::div[contains(@class,'monaco-editor')][1]"
                "//div[contains(@class,'view-lines')]"
            )
            if await view_lines.count() > 0:
                await view_lines.click()
            else:
                await textarea.first.click(force=True)
            await page.wait_for_timeout(300)
            await page.keyboard.press("Meta+a")
            await page.wait_for_timeout(100)
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(300)
            logger.info("Cleared preheader field (Meta+A, Backspace)")

            await _debug(page, "04_after_clear")

            # Read back the Monaco model value for this field before closing,
            # so we fail loudly here rather than discovering it after save.
            preheader_value = await page.evaluate("""
                (() => {
                    try {
                        const el = document.querySelector("[id*='preheader-input']");
                        if (!el) return null;
                        // Monaco textarea ids are on the hidden input; find the
                        // owning editor instance via the DOM ancestor and read
                        // its model value through the global monaco API.
                        const editors = window.monaco?.editor?.getEditors?.() || [];
                        for (const ed of editors) {
                            const node = ed.getDomNode();
                            if (node && node.contains(el)) {
                                return ed.getValue();
                            }
                        }
                        return null;
                    } catch (e) {
                        return 'ERROR:' + e.message;
                    }
                })()
            """)
            logger.info("Preheader Monaco model value after clear: %r", preheader_value)
            if preheader_value:
                raise RuntimeError(
                    f"Preheader field still has content after clear attempt: {preheader_value!r}"
                )

            # Close the sending info panel via "Done"
            try:
                done_btn = page.get_by_role("button", name="Done", exact=True)
                await done_btn.wait_for(state="visible", timeout=3000)
                await done_btn.click()
                await page.wait_for_timeout(1000)
                logger.info("Sending info panel closed via Done")
            except Exception as e:
                logger.warning("Could not click Done to close panel: %s", e)

            await _debug(page, "05_after_done")

            await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            braze_url = get_campaign_url_from_page(page.url) or page.url
            logger.info("Saved. URL: %s", braze_url)

            await _debug(page, "06_final")
            return braze_url

        finally:
            await context.close()
            await browser.close()


def main() -> None:
    logger.info("Clearing preheader on campaign %s...", CAMPAIGN_ID)
    braze_url = asyncio.run(clear_preheader())
    print(f"\nPreheader cleared. Campaign: {braze_url}")


if __name__ == "__main__":
    main()

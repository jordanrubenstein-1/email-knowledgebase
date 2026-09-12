#!/usr/bin/env python3
"""Fix missing body copy on the CZ Best Sellers SMS draft.

The campaign was auto-built with only the tracked link in the message body —
the copy line before it ("The Citizenry: Our best sellers are 25% off during
the Labor Day Event. Shop now:") never made it into the Monaco editor. This
navigates to the existing draft, reopens the message editor, and rewrites the
full body (copy + existing UTM-tagged link), then saves as draft.

Campaign: P_SMS_2026_09_11_CZ_Best_Sellers
Braze:    https://dashboard-07.braze.com/engagement/campaigns/6aa010bf10ca340088cc2b56/666672a4d8965b005ac6c1bd
Asana:    https://app.asana.com/1/5257710284167/project/1207353785125835/task/1218252877666759
"""
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_sms_campaign import configure_sms_content
from build_pt_campaign import save_as_draft, get_campaign_url_from_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND = "CZ"
CAMPAIGN_ID = "6aa010bf10ca340088cc2b56"
WORKSPACE_ID = "666672a4d8965b005ac6c1bd"

NEW_BODY = (
    "The Citizenry: Our best sellers are 25% off during the Labor Day Event. Shop now:\n"
    "https://www.the-citizenry.com/collections/all-best-sellers"
    "?utm_source=braze_CZ&utm_medium=sms&utm_campaign={{campaign.${name}}}"
)

SCRIPT_DIR = Path(__file__).parent


async def _debug(page, name: str) -> None:
    try:
        path = str(SCRIPT_DIR / f"screenshot_cz_best_sellers_sms_fix_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info("Screenshot: %s", path)
    except Exception:
        pass


async def edit_campaign() -> str:
    from playwright.async_api import async_playwright

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
                    continue

            await _debug(page, "02_after_edit_draft")

            # Navigate to Compose step
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

            await _debug(page, "03_compose_step")

            btn_texts = await page.evaluate("""() => {
                return [...document.querySelectorAll('button, a[role="button"]')]
                    .filter(el => el.offsetParent !== null)
                    .map(el => el.textContent.trim().substring(0, 50))
                    .filter(t => t.length > 0);
            }""")
            logger.info("Visible buttons: %s", btn_texts[:30])

            body_filled = await configure_sms_content(page, NEW_BODY)
            if not body_filled:
                raise RuntimeError("configure_sms_content could not verify the SMS body write")

            await _debug(page, "04_body_filled")

            await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            braze_url = get_campaign_url_from_page(page.url) or page.url
            logger.info("Saved. URL: %s", braze_url)

            await _debug(page, "05_final")
            return braze_url

        finally:
            await context.close()
            await browser.close()


def main() -> None:
    logger.info("Fixing campaign %s...", CAMPAIGN_ID)
    braze_url = asyncio.run(edit_campaign())
    print(f"\nEdit complete. Campaign: {braze_url}")


if __name__ == "__main__":
    main()

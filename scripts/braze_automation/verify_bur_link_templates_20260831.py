#!/usr/bin/env python3
"""
One-off verification: open the existing TEST_DELETE_ Burrow campaign
(created by test_bur_link_templates_20260831.py) and read back the Link
Management panel to confirm BOTH link templates show as selected.
"""

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("verify_bur_link_templates")

CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns/"
    "6a962128a698c600882960e8/67093a1f24ebbe0065cb9c77"
)


async def main() -> None:
    from playwright.async_api import async_playwright
    from login import create_context_with_session, login, save_session

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-save-password-bubble"])
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await login(page)
            await save_session(context)

            logger.info(f"Navigating to campaign: {CAMPAIGN_URL}")
            await page.goto(CAMPAIGN_URL, wait_until="load", timeout=20000)
            await page.wait_for_timeout(2000)

            # Land on Compose step
            for compose_name in ("Compose Messages", "Compose"):
                btn = page.get_by_role("button", name=compose_name)
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    logger.info(f"Clicked '{compose_name}'")
                    break

            # Open the HTML editor modal
            editor_opened = False
            for btn_name in ("Edit message", "Edit Message"):
                for sel in [
                    page.get_by_role("button", name=btn_name),
                    page.locator(f"button:has-text('{btn_name}')"),
                ]:
                    try:
                        if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                            await sel.first.click()
                            await page.wait_for_timeout(3000)
                            editor_opened = True
                            break
                    except Exception:
                        continue
                if editor_opened:
                    break
            if not editor_opened:
                raise RuntimeError("Could not open 'Edit message' modal")
            logger.info("Opened editor modal")

            # Open Link Management
            link_mgmt = page.get_by_text("Link Management", exact=True).first
            await link_mgmt.wait_for(state="visible", timeout=8000)
            await link_mgmt.click()
            await page.wait_for_timeout(3000)
            logger.info("Opened Link Management")

            # Read the selected-templates control text (e.g. "2 items selected")
            control = page.locator(".bcl-select__control").first
            control_text = (await control.inner_text()).strip() if await control.count() > 0 else "(no control found)"
            logger.info(f"Link templates control text: {control_text!r}")

            # Read each selected chip / value, if rendered as multi-value chips
            multi_values = page.locator(".bcl-select__multi-value")
            mv_count = await multi_values.count()
            names = []
            for i in range(mv_count):
                try:
                    names.append((await multi_values.nth(i).inner_text()).strip())
                except Exception:
                    pass
            logger.info(f"Multi-value chips ({mv_count}): {names}")

            # Also grab table column headers, which show one column per applied template
            headers = page.locator("th, [role='columnheader']")
            h_count = await headers.count()
            header_texts = []
            for i in range(h_count):
                try:
                    t = (await headers.nth(i).inner_text()).strip()
                    if t:
                        header_texts.append(t)
                except Exception:
                    pass
            logger.info(f"Table column headers: {header_texts}")

            screenshot_path = PROJECT_ROOT / "debug_bur_link_mgmt_verify.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Screenshot saved: {screenshot_path}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

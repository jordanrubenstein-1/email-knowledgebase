#!/usr/bin/env python3
"""Fix conversion events on the CZ Color Edit Sunwashed Isles draft campaign.

The campaign was duplicated from a legacy ref and inherited its conversion events.
This script navigates directly to the draft and updates the 4 existing slots
to the correct CZ values from brand_config.yaml — nothing else is touched.

Campaign: P_EM_2026_06_05_CZ_D_Color_Edit_Sunwashed_Isles
URL: https://dashboard-07.braze.com/engagement/campaigns/6a10d9e96a35d60085d860f1/666672a4d8965b005ac6c1bd
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "braze_automation"))

from playwright.async_api import async_playwright, Page
from braze_automation.login import ensure_logged_in, select_workspace, create_context_with_session
from braze_automation.build_pt_campaign import (
    _is_builtin_event,
    _select_conversion_event_type,
    _set_conversion_deadline,
    save_as_draft,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CAMPAIGN_URL = (
    "https://dashboard-07.braze.com/engagement/campaigns"
    "/6a10d9e96a35d60085d860f1/666672a4d8965b005ac6c1bd"
)
BRAND = "CZ"

# Correct CZ conversion events from data/brand_config.yaml
CONVERSIONS = {
    "A": {"event": "ecommerce.order_placed", "deadline_days": 3},
    "B": {"event": "Start session",           "deadline_days": 3},
    "C": {"event": "custom_product_view",     "deadline_days": 3},
    "D": {"event": "ecommerce.cart_updated",  "deadline_days": 3},
}


async def _navigate_to_conversions_step(page: Page) -> None:
    """Open the campaign for editing and land on the Assign Conversions step."""
    logger.info("Navigating to campaign...")
    await page.goto(CAMPAIGN_URL, wait_until="load", timeout=30000)
    await page.wait_for_timeout(2000)

    # Click edit button
    for btn_name in ("Edit Draft", "Edit Campaign", "Edit"):
        try:
            btn = page.get_by_role("button", name=btn_name)
            await btn.wait_for(state="visible", timeout=5000)
            await btn.click()
            await page.wait_for_timeout(2000)
            logger.info(f"Clicked '{btn_name}'")
            break
        except Exception:
            continue

    # Click the Assign Conversions step nav
    for nav_name in ("Assign Conversions", "Assign"):
        try:
            btn = page.get_by_role("button", name=nav_name)
            await btn.wait_for(state="visible", timeout=5000)
            await btn.click()
            await page.wait_for_timeout(2000)
            logger.info(f"Navigated to '{nav_name}' step")
            return
        except Exception:
            continue

    # Fallback: click any step labelled with conversion-related text
    try:
        link = page.get_by_text("Assign Conversions", exact=True)
        await link.wait_for(state="visible", timeout=5000)
        await link.click()
        await page.wait_for_timeout(2000)
        logger.info("Navigated via text link")
    except Exception as e:
        logger.warning(f"Could not navigate to conversions step: {e}")


async def _update_conversions_in_place(page: Page) -> None:
    """Configure all 4 conversion slots, adding any that don't already exist.

    Slot A is always present. For B–D: if the slot label isn't there yet,
    click "Add Conversion Event" first (same as build_pt_campaign does for
    fresh campaigns), then update the event type and deadline.
    """
    for idx, slot in enumerate(["A", "B", "C", "D"]):
        event_config = CONVERSIONS[slot]
        event_name = event_config["event"]
        deadline = event_config["deadline_days"]
        is_builtin, braze_label = _is_builtin_event(event_name)

        # Check whether this slot's label already exists on the page
        label_count = await page.get_by_text("Conversion event type", exact=True).count()
        if idx >= label_count:
            # Slot doesn't exist yet — add it
            add_btn = page.get_by_role("button", name="Add Conversion Event")
            try:
                await add_btn.scroll_into_view_if_needed()
                await add_btn.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Added conversion slot {slot}")
            except Exception as e:
                logger.warning(f"Could not add slot {slot}: {e}")
                continue

        if is_builtin:
            logger.info(f"Slot {slot}: {braze_label} (built-in), deadline={deadline}d")
        else:
            logger.info(f"Slot {slot}: Performs Custom Event → '{event_name}', deadline={deadline}d")

        await _select_conversion_event_type(page, idx, slot, is_builtin, braze_label, event_name)
        await _set_conversion_deadline(page, idx, slot, deadline)


async def main(dry_run: bool = False) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        await _navigate_to_conversions_step(page)
        await _update_conversions_in_place(page)

        if dry_run:
            logger.info("DRY RUN — not saving. Inspect the browser to verify.")
            input("Press Enter to close...")
        else:
            ok = await save_as_draft(page, dry_run=False)
            if ok:
                logger.info("Saved. Conversion events updated successfully.")
            else:
                logger.error("Save may have failed — check the browser.")

        await browser.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))

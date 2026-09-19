"""One-off fix for draft P_EM_2026_05_12_HAV_CONV_D_Mp_Memorial_Day_Ea_Final.

Fixes:
1. Rename to P_EM_2026_05_12_HAV_CONV_D_Memorial_Day_EA_Final
2. Swap hero image to the already-uploaded CDN asset
3. Remove "Targeted Send List - Converted" filter row, keep only
   "Daily Send List - Converted" as the audience segment
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "braze_automation"))

# Load .env from project root before importing braze_automation modules
from dotenv import load_dotenv
_project_root = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(_project_root, ".env"), override=True)

from build_designed_campaign import (
    set_campaign_name,
    swap_hero_image_in_dnd,
    find_first_image_src,
    get_campaign_html,
    find_campaign_api_id_by_name,
    configure_audience_designed,
    save_as_draft,
)
from login import ensure_logged_in, select_workspace, create_context_with_session
from playwright.async_api import async_playwright

BRAND = "HAV"
OLD_NAME = "P_EM_2026_05_12_HAV_CONV_D_Mp_Memorial_Day_Ea_Final"
NEW_NAME = "P_EM_2026_05_12_HAV_CONV_D_Memorial_Day_EA_Final"
CAMPAIGN_INTERNAL_ID = "69fe6d6e7b4c2500817facc8"
WORKSPACE_ID = "664223fb71bcf3005760dfc2"  # HAV workspace
CDN_URL = "https://braze-images.com/appboy/communication/assets/image_assets/images/69fe6d555de16f00830b9909/original.png"
CAMPAIGN_URL = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_INTERNAL_ID}/{WORKSPACE_ID}"


async def main():
    # --- 1. Look up the draft's hero image src via the API ---
    print("Looking up campaign API ID for old name...")
    api_id = find_campaign_api_id_by_name(OLD_NAME, BRAND)
    if not api_id:
        print(f"Could not find campaign '{OLD_NAME}' via API — trying new name...")
        api_id = find_campaign_api_id_by_name(NEW_NAME, BRAND)
    if not api_id:
        print("WARNING: Could not find campaign via API — image swap will be skipped")

    banner_src = None
    if api_id:
        html = get_campaign_html(api_id, BRAND)
        if html:
            banner_src = find_first_image_src(html)
            print(f"Hero image src: {banner_src}")
        else:
            print("WARNING: Could not fetch campaign HTML — image swap will be skipped")

    # --- 2. Launch browser and fix the draft ---
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-save-password-bubble"],
        )
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        print(f"Navigating to campaign: {CAMPAIGN_URL}")
        await page.goto(CAMPAIGN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # --- 3. Rename ---
        print(f"Renaming to: {NEW_NAME}")
        await set_campaign_name(page, NEW_NAME)

        # --- 4. Swap hero image ---
        if banner_src and CDN_URL:
            print(f"Swapping image: {banner_src[:60]} → {CDN_URL[:60]}")
            swapped = await swap_hero_image_in_dnd(page, banner_src, CDN_URL)
            if swapped:
                print("Image swapped successfully")
            else:
                print("WARNING: Image swap failed — check debug screenshots")
        else:
            print("Skipping image swap (no src or CDN URL)")

        # --- 5. Fix audience: remove filter, ensure correct segment ---
        print("Fixing audience...")
        await configure_audience_designed(
            page,
            desired_segment_type="full_file",
            ref_segment_type=None,
            brand=BRAND,
            hav_variant="CONV",
        )
        print("Audience configured: Daily Send List - Converted (no filters)")

        # --- 6. Save draft ---
        print("Saving draft...")
        await save_as_draft(page, dry_run=False)
        print(f"Done. Campaign URL: {CAMPAIGN_URL}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

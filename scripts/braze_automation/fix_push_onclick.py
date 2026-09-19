"""Fix on-click URL for HAV DPS push campaigns where it wasn't set during build."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CAMPAIGNS = [
    ("6a1f33ec1ec8fc00831a5dd0", "P_PUSH_2026_06_05_HAV_PC_Fourth_Of_July_Event_Launch"),
    ("6a1f346a2363a70082c80616", "P_PUSH_2026_06_10_HAV_PC_Fourth_Of_July_Sale_Reminder"),
    ("6a1f356c64cd980081ca011c", "P_PUSH_2026_06_18_HAV_PC_Fourth_Of_July_Sale_Reminder"),
]

HAV_WORKSPACE = "664223fb71bcf3005760dfc2"
DPS_DEEP_LINK = "https://havenly.com?utm_source=braze_havenly&utm_campaign={{campaign.$(name)}}&utm_medium=push&utm_content=pre_converted#packages-section"


async def main():
    from playwright.async_api import async_playwright
    from login import login, save_session, select_workspace, create_context_with_session
    from build_push_campaign import set_push_on_click_behavior
    from build_pt_campaign import save_as_draft

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-save-password-bubble"])
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await login(page)
        await save_session(context)
        await select_workspace(page, "HAV")

        for campaign_id, campaign_name in CAMPAIGNS:
            print(f"\n--- {campaign_name} ---")
            url = f"https://dashboard-07.braze.com/engagement/campaigns/{campaign_id}/{HAV_WORKSPACE}"
            await page.goto(url, wait_until="load", timeout=20000)

            # Navigate to Compose Messages step
            for selector in [
                page.get_by_text("Compose Messages", exact=True),
                page.get_by_role("button", name="Compose Messages"),
                page.get_by_role("button", name="Compose"),
            ]:
                try:
                    await selector.click(timeout=3000)
                    break
                except Exception:
                    pass

            await page.wait_for_timeout(1500)

            success = await set_push_on_click_behavior(page, DPS_DEEP_LINK)
            if success:
                print(f"  ✓ On-click URL set")
                await save_as_draft(page, dry_run=False)
                print(f"  ✓ Saved as draft")
            else:
                print(f"  ✗ Failed — needs manual fix in Braze")

        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

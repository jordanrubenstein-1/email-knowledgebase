"""Verify the on-click URL was saved correctly on one campaign."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from playwright.async_api import async_playwright
    from login import login, save_session, select_workspace, create_context_with_session
    from pathlib import Path
    from datetime import datetime

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await login(page)
        await select_workspace(page, "HAV")

        url = "https://dashboard-07.braze.com/engagement/campaigns/6a1f33ec1ec8fc00831a5dd0/664223fb71bcf3005760dfc2"
        await page.goto(url, wait_until="load", timeout=20000)
        for sel in [page.get_by_text("Compose Messages", exact=True), page.get_by_role("button", name="Compose Messages")]:
            try:
                await sel.click(timeout=3000); break
            except: pass
        await page.wait_for_timeout(2000)
        path = Path(__file__).parent / f"verify_onclick_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(path), full_page=False)
        print(f"Screenshot: {path}")

asyncio.run(main())

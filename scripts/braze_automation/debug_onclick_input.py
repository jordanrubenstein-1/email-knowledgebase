"""Debug: find exactly which input _find_url_input is selecting and what its value is."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from playwright.async_api import async_playwright
    from login import login, select_workspace, create_context_with_session
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
            try: await sel.click(timeout=3000); break
            except: pass
        await page.wait_for_timeout(2000)

        # Count how many times "On-click behavior" appears
        count = await page.get_by_text("On-click behavior", exact=False).count()
        print(f"'On-click behavior' text count: {count}")

        # Check each occurrence
        for i in range(count):
            el = page.get_by_text("On-click behavior", exact=False).nth(i)
            try:
                tag = await el.evaluate("el => el.tagName")
                text = await el.inner_text()
                print(f"  [{i}] <{tag}> text={text!r}")
                # Find following input
                inp = el.locator("xpath=following::input[1]")
                if await inp.count() > 0:
                    val = await inp.first.input_value()
                    ph = await inp.first.get_attribute("placeholder")
                    aria = await inp.first.get_attribute("aria-label")
                    visible = await inp.first.is_visible()
                    print(f"       → following input[1]: value={val!r}, placeholder={ph!r}, aria={aria!r}, visible={visible}")
            except Exception as e:
                print(f"  [{i}] error: {e}")

        # Also check all visible inputs on page
        print("\nAll visible inputs on page:")
        inputs = page.locator("input:visible")
        n = await inputs.count()
        for i in range(min(n, 20)):
            inp = inputs.nth(i)
            try:
                val = await inp.input_value()
                ph = await inp.get_attribute("placeholder")
                aria = await inp.get_attribute("aria-label")
                typ = await inp.get_attribute("type")
                print(f"  input[{i}]: type={typ!r} placeholder={ph!r} aria={aria!r} value={val!r}")
            except: pass

asyncio.run(main())

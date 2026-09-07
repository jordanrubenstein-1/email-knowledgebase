"""Find Monaco editor index for the on-click URL field."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from playwright.async_api import async_playwright
    from login import login, select_workspace, create_context_with_session

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await create_context_with_session(browser)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await login(page)
        await select_workspace(page, "HAV")
        await page.goto("https://dashboard-07.braze.com/engagement/campaigns/6a1f33ec1ec8fc00831a5dd0/664223fb71bcf3005760dfc2", wait_until="load", timeout=20000)
        for sel in [page.get_by_text("Compose Messages", exact=True), page.get_by_role("button", name="Compose Messages")]:
            try: await sel.click(timeout=3000); break
            except: pass
        await page.wait_for_timeout(2000)

        result = await page.evaluate("""() => {
            const editors = window.monaco?.editor?.getEditors?.() || [];
            const models = window.monaco?.editor?.getModels?.() || [];
            return {
                editorCount: editors.length,
                modelCount: models.length,
                editorValues: editors.map((e, i) => ({i, val: e.getValue().substring(0, 100)})),
                modelValues: models.map((m, i) => ({i, uri: m.uri?.toString(), val: m.getValue().substring(0, 100)}))
            };
        }""")
        import json
        print(json.dumps(result, indent=2))

asyncio.run(main())

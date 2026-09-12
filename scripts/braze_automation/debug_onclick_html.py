"""Find where the on-click URL actually lives in the DOM."""
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

        # Search all elements for havenly.com text
        result = await page.evaluate("""() => {
            const results = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ALL);
            let node;
            while (node = walker.nextNode()) {
                const val = node.value || node.textContent || node.getAttribute?.('value') || '';
                if (val && val.includes('havenly.com')) {
                    const tag = node.tagName || 'TEXT';
                    const aria = node.getAttribute?.('aria-label') || '';
                    const ph = node.getAttribute?.('placeholder') || '';
                    const type = node.getAttribute?.('type') || '';
                    const domVal = node.value || '';
                    const text = (node.textContent || '').substring(0, 100);
                    results.push({tag, aria, ph, type, domVal, text: text.trim()});
                }
            }
            return results;
        }""")
        print(f"Elements containing 'havenly.com': {len(result)}")
        for r in result:
            print(f"  <{r['tag']}> aria={r['aria']!r} type={r['type']!r} domVal={r['domVal']!r} text={r['text'][:80]!r}")

asyncio.run(main())

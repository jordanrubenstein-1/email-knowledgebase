"""Find the exact element to click/type in for the on-click URL."""
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

        # Find the Push destination input and its parent chain
        result = await page.evaluate("""() => {
            const input = document.querySelector('input[aria-label="Push destination"]');
            if (!input) return {error: 'not found'};

            // Walk up to find interesting ancestors
            const ancestors = [];
            let el = input;
            for (let i = 0; i < 10; i++) {
                el = el.parentElement;
                if (!el) break;
                ancestors.push({
                    tag: el.tagName,
                    class: el.className?.substring(0, 60),
                    role: el.getAttribute('role'),
                    contenteditable: el.getAttribute('contenteditable'),
                    text: el.textContent?.substring(0, 80)?.trim()
                });
            }

            // Also check siblings
            const parent = input.parentElement;
            const siblings = parent ? Array.from(parent.children).map(c => ({
                tag: c.tagName,
                class: c.className?.substring(0, 40),
                contenteditable: c.getAttribute('contenteditable'),
                text: c.textContent?.substring(0, 60)?.trim()
            })) : [];

            return {
                input: {
                    type: input.type,
                    value: input.value,
                    class: input.className?.substring(0, 60)
                },
                ancestors,
                siblings
            };
        }""")
        import json
        print(json.dumps(result, indent=2))

asyncio.run(main())

"""Find the exact element containing the on-click URL and its parent structure."""
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
            // Find the span containing the URL text
            const spans = Array.from(document.querySelectorAll('span'));
            const urlSpan = spans.find(s => s.textContent?.includes('havenly.com/exp'));
            if (!urlSpan) return {error: 'url span not found'};

            // Walk up to find the clickable/input ancestor
            const info = [];
            let el = urlSpan;
            for (let i = 0; i < 15; i++) {
                info.push({
                    tag: el.tagName,
                    class: (el.className || '').substring(0, 80),
                    role: el.getAttribute?.('role'),
                    contenteditable: el.getAttribute?.('contenteditable'),
                    aria: el.getAttribute?.('aria-label'),
                    id: el.id,
                    text: (el.textContent || '').substring(0, 60).trim()
                });
                el = el.parentElement;
                if (!el) break;
            }

            // Also find all inputs/textareas/contenteditables in the interactions fieldset
            const fieldset = document.querySelector('fieldset');
            const interactable = fieldset ? Array.from(fieldset.querySelectorAll(
                'input, textarea, [contenteditable], [role="textbox"]'
            )).map(e => ({
                tag: e.tagName,
                type: e.type,
                value: e.value,
                aria: e.getAttribute('aria-label'),
                contenteditable: e.getAttribute('contenteditable'),
                role: e.getAttribute('role'),
                class: (e.className || '').substring(0, 60),
                text: (e.textContent || '').substring(0, 60).trim()
            })) : [];

            return {urlSpanAncestors: info, interactableInFieldset: interactable};
        }""")
        import json
        print(json.dumps(result, indent=2))

asyncio.run(main())

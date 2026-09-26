#!/usr/bin/env python3
"""
Explore the James Ottoman PDP:
- Intercept network requests to find where fabric images come from
- Wait for React to hydrate, then inspect swatch elements
- Click fabric swatches and capture resulting image URLs

Run: uv run python scripts/explore_james_otto_pdp.py
"""
import asyncio
import json
import re
from playwright.async_api import async_playwright

BASE_URL = (
    "https://www.interiordefine.com/living/all-custom-ottomans/"
    "james-storage-square-ottoman"
    "?material-type=147540&options-5279=98562&options-5280=147540"
    "&options-5281=98670&options-5282=98672"
)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        # ── Intercept requests ────────────────────────────────────────────────
        captured = {"graphql": [], "images": [], "api": []}

        async def on_response(response):
            url = response.url
            if "graphql" in url.lower():
                try:
                    body = await response.json()
                    captured["graphql"].append({"url": url, "body": body})
                except Exception:
                    pass
            elif any(url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if "catalog/product" in url:
                    captured["images"].append(url)
            elif "/rest/" in url or "/api/" in url:
                try:
                    body = await response.text()
                    captured["api"].append({"url": url, "body": body[:500]})
                except Exception:
                    pass

        page.on("response", on_response)

        print("Loading page...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

        # Wait for React to hydrate — look for a swatch or configurator element
        print("Waiting for React hydration...")
        try:
            await page.wait_for_selector(
                "button[class*='swatch'], [data-option-id], "
                "[class*='FabricSelector'], [class*='fabricSelector'], "
                "[class*='ColorSwatch'], div[role='button'][class*='swatch'], "
                ".configurator button, .product-options-wrapper, "
                ".customizer, [class*='customizer']",
                timeout=15000,
            )
            print("Configurator element found!")
        except Exception:
            print("Configurator selector timed out — waiting extra time...")
            await page.wait_for_timeout(8000)

        # ── Inspect what swatch elements exist ───────────────────────────────
        print("\n=== SWATCH DOM SCAN ===")
        swatch_info = await page.evaluate("""() => {
            const result = { total_btns: 0, total_divs: 0, found: [] };

            // Get all clickable elements with swatch-like text or classes
            const all = document.querySelectorAll('button, div[role="button"], [tabindex]');
            result.total_btns = all.length;

            for (const el of all) {
                const cls = el.className || '';
                const txt = (el.textContent || '').slice(0, 30);
                const did = el.getAttribute('data-option-id') || '';
                const ariaLabel = el.getAttribute('aria-label') || '';

                if (cls.toLowerCase().includes('swatch') ||
                    cls.toLowerCase().includes('fabric') ||
                    cls.toLowerCase().includes('color') ||
                    did ||
                    (ariaLabel && ariaLabel.length < 30)) {
                    result.found.push({
                        tag: el.tagName,
                        cls: cls.slice(0, 100),
                        did,
                        ariaLabel,
                        txt: txt.trim(),
                        style: (el.getAttribute('style') || '').slice(0, 80),
                    });
                }
            }
            return result;
        }""")
        print(f"Total buttons/interactive: {swatch_info['total_btns']}")
        print(f"Swatch-like elements found: {len(swatch_info['found'])}")
        for s in swatch_info["found"][:20]:
            print(f"  {s}")

        # ── Check page structure for React state ─────────────────────────────
        print("\n=== PAGE TITLE / H1 ===")
        title = await page.title()
        h1 = await page.locator("h1").first.text_content()
        print(f"Title: {title}")
        print(f"H1: {h1}")

        # ── Look at all img tags (both src and data-src) ──────────────────────
        print("\n=== ALL IMG TAGS (including data-src / lazy) ===")
        img_scan = await page.evaluate("""() => {
            const result = [];
            for (const img of document.querySelectorAll('img')) {
                const src    = img.src || '';
                const dsrc   = img.getAttribute('data-src') || '';
                const orig   = img.getAttribute('data-original') || '';
                const zoom   = img.getAttribute('data-zoom-image') || '';
                const srcset = img.srcset || '';
                const cls    = img.className.slice(0, 80);
                const id_    = img.id;

                if (src.includes('jmes') || src.includes('james') ||
                    dsrc.includes('jmes') || orig.includes('jmes') ||
                    zoom.includes('jmes') ||
                    (src.includes('catalog/product') && !src.includes('swatches'))) {
                    result.push({ src: src.slice(0,120), dsrc: dsrc.slice(0,120),
                                  orig: orig.slice(0,80), zoom: zoom.slice(0,80),
                                  cls, id: id_, srcset: srcset.slice(0,80) });
                }
            }
            return result;
        }""")
        print(f"James/catalog product imgs: {len(img_scan)}")
        for img in img_scan[:15]:
            print(f"  {img}")

        # ── Inspect inline <script> and __NEXT_DATA__ ─────────────────────────
        print("\n=== NEXT_DATA / INLINE JSON ===")
        nextdata = await page.evaluate("""() => {
            const el = document.getElementById('__NEXT_DATA__');
            if (el) return el.textContent.slice(0, 2000);
            // Also check for window.__INITIAL_STATE__
            const scripts = document.querySelectorAll('script:not([src])');
            for (const s of scripts) {
                const t = s.textContent || '';
                if (t.includes('jmes') || t.includes('JMES')) {
                    return t.slice(0, 1000);
                }
            }
            return null;
        }""")
        if nextdata:
            print(f"Found: {nextdata[:500]}")
        else:
            print("No __NEXT_DATA__ or JMES script found")

        # ── Show all captured network data ────────────────────────────────────
        print(f"\n=== NETWORK: GraphQL calls: {len(captured['graphql'])} ===")
        for gql in captured["graphql"][:3]:
            body_str = json.dumps(gql["body"])[:300]
            print(f"  URL: {gql['url']}")
            print(f"  Body: {body_str}")

        print(f"\n=== NETWORK: Product images loaded ({len(captured['images'])}) ===")
        for img_url in captured["images"][:20]:
            print(f"  {img_url}")

        print(f"\n=== NETWORK: REST/API calls: {len(captured['api'])} ===")
        for api in captured["api"][:5]:
            print(f"  {api['url']}")
            print(f"  → {api['body'][:200]}")

        # ── Take a screenshot for visual inspection ───────────────────────────
        screenshot_path = "scripts/james_otto_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=False)
        print(f"\nScreenshot saved: {screenshot_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

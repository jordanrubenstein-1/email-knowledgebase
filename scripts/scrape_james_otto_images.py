#!/usr/bin/env python3
"""
Scrape James Ottoman per-fabric product images from interiordefine.com PDP.

Strategy:
  - For each fabric, load the PDP with that fabric pre-selected via URL params
  - Wait for the product image to load/update
  - Capture the image src URL
  - Write fabric_code -> image_url mapping to data/james_otto_images.csv

Output: data/james_otto_images.csv
        data/braze_catalogs/otto_images.csv  (Braze catalog-ready)
"""

import asyncio
import csv
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = "https://www.interiordefine.com/living/all-custom-ottomans/james-storage-square-ottoman"
FIXED_PARAMS_PARTS = {
    "5279": "98562",   # Depth attribute → Depth 26
    "5281": "98670",   # Storage option → No Storage Top
    "5282": "98672",   # Piping option → No Piping
}
FABRIC_ATTR_ID = "5280"

# 35 JMES_OTTO fabrics: (fabric_code, material_type_id)
FABRICS = [
    ("MER-006", 147540),
    ("SE-172",  585115),
    ("KEY-014",  98645),
    ("HS-002",  155261),
    ("ROY-008",  98663),
    ("ROY-004",  98639),
    ("SE-168",   98578),
    ("MER-001", 106658),
    ("SE-173",   98669),
    ("MER-002", 107426),
    ("SE-170",   98581),
    ("SE-171",   98667),
    ("SE-166",   98579),
    ("ROY-010",  98665),
    ("MER-003", 105935),
    ("ROY-009",  98664),
    ("ROY-005",  98640),
    ("COV-025", 118577),
    ("SE-167",   98583),
    ("ROY-006",  98641),
    ("ROY-007",  98662),
    ("FST-026", 320287),
    ("CAS-016", 141988),
    ("COV-007",  98648),
    ("CAS-010", 141011),
    ("SE-181",  625121),
    ("SE-164",   98580),
    ("GIA-005", 142470),
    ("COV-014", 268648),
    ("SE-180",  624366),
    ("SE-179",  325087),
    ("MER-008", 254116),
    ("GIA-035", 578039),
    ("AK-618-53", 98598),
    ("MER-005", 564673),
]

# Image selectors to try, in priority order
IMG_SELECTORS = [
    ".fotorama__stage img.fotorama__img",
    ".product-image-photo",
    ".fotorama__img--full",
    ".fotorama__img",
    "[data-role='product-main-image'] img",
    ".gallery-placeholder__image",
    ".product-image img",
    "img.product-image-photo",
]

# Minimum URL fragment to confirm it's a product (not a spinner/placeholder)
PRODUCT_IMG_HINTS = ["catalog/product", "media/catalog", "interiordefine.com/media"]

STATIC_FALLBACK = (
    "https://www.interiordefine.com/media/catalog/product/j/m/"
    "jmes.fabric.otto.square.storage_1.jpg?store=default&image-type=image"
)


def make_pdp_url(material_type_id: int) -> str:
    params = (
        f"material-type={material_type_id}"
        f"&options-5279=98562"
        f"&options-{FABRIC_ATTR_ID}={material_type_id}"
        f"&options-5281=98670"
        f"&options-5282=98672"
    )
    return f"{BASE_URL}?{params}"


async def capture_image(page, fabric_code: str, material_type_id: int) -> str | None:
    url = make_pdp_url(material_type_id)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Let React hydrate + image swap settle
        await page.wait_for_timeout(3000)
    except PlaywrightTimeout:
        print(f"  TIMEOUT navigating to {fabric_code}")
        return None
    except Exception as e:
        print(f"  ERROR navigating to {fabric_code}: {e}")
        return None

    # Try each selector
    for sel in IMG_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                src = await loc.get_attribute("src") or ""
                if src and any(h in src for h in PRODUCT_IMG_HINTS):
                    return src
        except Exception:
            continue

    # Fallback: scan all <img> tags for a catalog URL
    try:
        imgs = await page.locator("img").all()
        for img in imgs:
            src = await img.get_attribute("src") or ""
            if any(h in src for h in PRODUCT_IMG_HINTS) and "placeholder" not in src.lower():
                return src
    except Exception:
        pass

    return None


async def explore_page(page, url: str) -> dict:
    """First pass: dump selectors found on the page so we can tune."""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(4000)

    found = {}
    for sel in IMG_SELECTORS:
        try:
            count = await page.locator(sel).count()
            if count:
                first = page.locator(sel).first
                src = await first.get_attribute("src") or ""
                found[sel] = {"count": count, "src": src[:120]}
        except Exception as e:
            found[sel] = {"error": str(e)}

    # Also capture all img srcs that look like product images
    all_product_imgs = []
    try:
        imgs = await page.locator("img").all()
        for img in imgs:
            src = await img.get_attribute("src") or ""
            if any(h in src for h in PRODUCT_IMG_HINTS):
                all_product_imgs.append(src[:120])
    except Exception:
        pass

    found["_all_product_imgs"] = all_product_imgs
    return found


async def main(explore_only: bool = False):
    project_root = Path(__file__).parent.parent
    output_dir = project_root / "data"
    output_dir.mkdir(exist_ok=True)

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

        # Exploration pass: first fabric (MER-006 / 147540)
        if explore_only:
            print("=== EXPLORE MODE — first fabric only ===")
            explore_url = make_pdp_url(FABRICS[0][1])
            print(f"URL: {explore_url}")
            result = await explore_page(page, explore_url)
            import json
            print(json.dumps(result, indent=2))
            await browser.close()
            return

        # Full scrape
        results = []
        print(f"Scraping {len(FABRICS)} fabrics...\n")

        for i, (fabric_code, material_type_id) in enumerate(FABRICS, 1):
            print(f"[{i:02d}/{len(FABRICS)}] {fabric_code} ({material_type_id})")
            image_url = await capture_image(page, fabric_code, material_type_id)
            if image_url:
                print(f"  ✓ {image_url[:80]}")
            else:
                image_url = STATIC_FALLBACK
                print(f"  ✗ fallback → static image")

            results.append({
                "fabric_code": fabric_code,
                "material_type_id": material_type_id,
                "image_url": image_url,
            })

        await browser.close()

    # Write raw output
    raw_path = output_dir / "james_otto_images.csv"
    with open(raw_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fabric_code", "material_type_id", "image_url"])
        writer.writeheader()
        writer.writerows(results)
    print(f"\n✓ Raw data → {raw_path}")

    # Write Braze catalog (otto_images)
    catalog_path = output_dir / "braze_catalogs" / "otto_images.csv"
    with open(catalog_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "product", "fabric_code", "image_url"])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "id": f"JMES_OTTO_{r['fabric_code']}",
                "product": "JMES_OTTO",
                "fabric_code": r["fabric_code"],
                "image_url": r["image_url"],
            })
    print(f"✓ Braze catalog → {catalog_path}")

    found = sum(1 for r in results if r["image_url"] != STATIC_FALLBACK)
    print(f"\n{found}/{len(FABRICS)} per-color images captured")
    misses = [r["fabric_code"] for r in results if r["image_url"] == STATIC_FALLBACK]
    if misses:
        print(f"Fallback (static): {misses}")

    return results


if __name__ == "__main__":
    explore = "--explore" in sys.argv
    asyncio.run(main(explore_only=explore))

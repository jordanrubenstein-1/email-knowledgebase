#!/usr/bin/env python3
"""
Swap image slices in an existing Braze designed-email draft campaign.

Images are already hosted on Braze CDN — no upload step needed.
Pairs new URLs positionally with existing image srcs (top→bottom in the email).

Usage:
    uv run python scripts/braze_automation/swap_campaign_slices.py \
      --campaign-name "P_EM_2026_05_21_CZ_PC_D_Summer_Trend_Forecast" \
      --brand CZ \
      --image-urls URL1 URL2 URL3 URL4 URL5 URL6 URL7

    # Dry run (parse + print pairs, no browser):
    uv run python scripts/braze_automation/swap_campaign_slices.py \
      --campaign-name "..." --brand CZ --image-urls URL1 ... --dry-run
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright, TimeoutError as PlaywrightTimeout

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

# Locate .env — it lives in the main checkout, not in git worktrees (gitignored).
# Walk up from PROJECT_ROOT until we find it.
_env_path = PROJECT_ROOT / ".env"
if not _env_path.exists():
    for _parent in PROJECT_ROOT.parents:
        _candidate = _parent / ".env"
        if _candidate.exists():
            _env_path = _candidate
            break
load_dotenv(_env_path)

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_designed_campaign import (
    find_campaign_api_id_by_name,
    get_campaign_html,
    _find_email_row_by_name,
    _search_with_enter,
    _close_dnd_editor,
    _url_filename,
)
from build_push_campaign import navigate_to_campaigns_list, _set_status_filter
from build_pt_campaign import save_as_draft, capture_screenshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def find_all_image_srcs(html: str) -> List[str]:
    """Return src URLs of all content images in the email HTML, in DOM order.

    Skips data URIs, Liquid variables, and tracking pixels (both dims < 5px).
    """
    img_pattern = re.compile(r'<img\s([^>]+)>', re.IGNORECASE | re.DOTALL)
    src_pattern = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
    height_pattern = re.compile(r'\bheight=["\']?(\d+)["\']?', re.IGNORECASE)
    width_pattern = re.compile(r'\bwidth=["\']?(\d+)["\']?', re.IGNORECASE)

    srcs = []
    for m in img_pattern.finditer(html):
        attrs = m.group(1)
        src_m = src_pattern.search(attrs)
        if not src_m:
            continue
        src = src_m.group(1)
        if src.startswith("data:") or "{{" in src:
            continue
        height_m = height_pattern.search(attrs)
        height = int(height_m.group(1)) if height_m else None
        width_m = width_pattern.search(attrs)
        width = int(width_m.group(1)) if width_m else None
        if height is not None and height < 5 and width is not None and width < 5:
            continue
        srcs.append(src)

    logger.info(f"Found {len(srcs)} content images in campaign HTML")
    return srcs


# ---------------------------------------------------------------------------
# Campaign navigation
# ---------------------------------------------------------------------------

async def open_existing_campaign_editor(
    page: Page, campaign_name: str, brand: str
) -> bool:
    """Find an existing campaign by name and open its editor.

    Searches Draft status first, then All. Clicks the campaign name link
    to enter edit mode (draft campaigns open directly in the editor).
    Returns True if the campaign editor page loaded.
    """
    await navigate_to_campaigns_list(page, brand=brand)

    # Wait for the search box to be ready (same pattern as search_and_duplicate_email_campaign)
    for _attempt in range(10):
        try:
            await page.wait_for_selector(
                "input[placeholder*='Search' i], input[type='search']",
                state="visible",
                timeout=3000,
            )
            break
        except Exception:
            await page.wait_for_timeout(1000)

    for status in ("Draft", "All", "Active", "Idle", "Stopped"):
        logger.info(f"Searching for '{campaign_name}' under Status: {status}...")
        await _set_status_filter(page, status)
        await _search_with_enter(page, campaign_name)

        # Try to find and click the campaign name link directly
        try:
            name_el = page.get_by_text(campaign_name, exact=True).first
            if await name_el.count() > 0 and await name_el.is_visible(timeout=3000):
                await name_el.click()
                await page.wait_for_timeout(4000)
                if "/campaigns/" in page.url:
                    logger.info(f"Opened campaign editor: {page.url}")
                    return True
        except Exception as e:
            logger.debug(f"Direct name click failed under {status}: {e}")

        # Fallback: find the row, then click the first link in it
        row = await _find_email_row_by_name(page, campaign_name)
        if row:
            try:
                link = row.locator("a").first
                if await link.count() > 0:
                    await link.click()
                    await page.wait_for_timeout(4000)
                    if "/campaigns/" in page.url:
                        logger.info(f"Opened campaign editor via row link: {page.url}")
                        return True
            except Exception as e:
                logger.debug(f"Row link click failed under {status}: {e}")

    logger.error(f"Could not find campaign '{campaign_name}' to open")
    return False


async def navigate_to_compose_step(page: Page) -> bool:
    """Ensure we're on the Compose step of the campaign editor.

    If we're on an Overview/Analytics page, click the Compose tab or
    'Edit Campaign' button to enter edit mode.
    """
    # Check if "Edit message" is already visible (already on Compose step)
    edit_msg = page.get_by_role("button", name="Edit message")
    try:
        if await edit_msg.count() > 0 and await edit_msg.first.is_visible(timeout=2000):
            logger.info("Already on Compose step")
            return True
    except Exception:
        pass

    # Try clicking "Edit Campaign" button (overview page for draft campaigns)
    for btn_text in ("Edit Campaign", "Edit campaign", "Edit"):
        try:
            btn = page.get_by_role("button", name=btn_text, exact=True)
            if await btn.count() > 0 and await btn.first.is_visible(timeout=2000):
                await btn.first.click()
                await page.wait_for_timeout(3000)
                logger.info(f"Clicked '{btn_text}' to enter edit mode")
                return True
        except Exception:
            pass

    # Try clicking a "Compose" step tab / breadcrumb
    for label in ("Compose Messages", "Compose", "1"):
        try:
            tab = page.get_by_role("tab", name=label)
            if await tab.count() > 0 and await tab.first.is_visible(timeout=1000):
                await tab.first.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Clicked compose tab: {label!r}")
                return True
        except Exception:
            pass

    logger.warning("Could not confirm Compose step — proceeding anyway")
    return True


# ---------------------------------------------------------------------------
# DnD image swap
# ---------------------------------------------------------------------------

async def _swap_single_image_in_bee(
    page: Page,
    bee_frame,
    old_src: str,
    new_url: str,
    idx: int,
) -> bool:
    """Click an image in the BEE editor by its current src and update its URL.

    Leaves the editor open. Returns True if the URL was successfully updated.
    """
    src_filename = _url_filename(old_src)
    clicked = False

    all_frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
    for frame in all_frames:
        for sel_str in [
            f'img[src="{old_src}"]',
            f'img[src*="{src_filename}"]',
        ]:
            try:
                img = frame.locator(sel_str)
                if await img.count() > 0:
                    await img.first.scroll_into_view_if_needed()
                    await img.first.click()
                    await page.wait_for_timeout(1500)
                    logger.info(f"[Slice {idx+1}] Clicked image ({sel_str[:60]})")
                    clicked = True
                    break
            except Exception as e:
                logger.debug(f"Click attempt failed ({sel_str}): {e}")
        if clicked:
            break

    if not clicked:
        logger.error(f"[Slice {idx+1}] Could not click image with src: {old_src[:80]}")
        return False

    # Wait for properties panel to update
    await page.wait_for_timeout(1000)

    # Re-find the BEE frame in case it changed after click
    if bee_frame is None:
        for frame in page.frames:
            if "getbee.io" in frame.url:
                bee_frame = frame
                break

    cdn_url_js = new_url.replace("'", "\\'")
    updated = False

    # Strategy A: Playwright .fill() on the BEE URL text input
    if bee_frame:
        try:
            first_text = bee_frame.locator("input[type='text']").first
            if await first_text.count() > 0:
                current_val = await first_text.input_value()
                if "braze-images" in current_val or "appboy/communication" in current_val:
                    await first_text.click()
                    await first_text.fill(new_url)
                    await first_text.press("Tab")
                    await page.wait_for_timeout(500)
                    logger.info(
                        f"[Slice {idx+1}] URL updated via .fill() "
                        f"(was: {current_val[:60]})"
                    )
                    updated = True
        except Exception as e:
            logger.debug(f"[Slice {idx+1}] .fill() failed: {e}")

    # Strategy B: JS native value setter + React synthetic events
    if bee_frame and not updated:
        try:
            updated = await bee_frame.evaluate(f"""() => {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.value && (
                        inp.value.includes('braze-images') ||
                        inp.value.includes('appboy/communication')
                    )) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, '{cdn_url_js}');
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true}}));
                        return true;
                    }}
                }}
                return false;
            }}""")
            if updated:
                logger.info(f"[Slice {idx+1}] URL updated via JS native setter")
                await page.wait_for_timeout(500)
        except Exception as e:
            logger.debug(f"[Slice {idx+1}] JS setter failed: {e}")

    if not updated:
        logger.error(f"[Slice {idx+1}] Could not update URL in BEE editor")

    return updated


async def swap_all_images_in_dnd(
    page: Page, pairs: List[Tuple[str, str]]
) -> Tuple[int, int]:
    """Open the DnD editor once, swap all (old_src, new_url) pairs, close editor.

    Returns (success_count, total_count).
    """
    logger.info(f"Opening DnD editor to swap {len(pairs)} image(s)...")

    # Open the DnD editor via "Edit message"
    edit_btn_selectors = [
        page.get_by_role("button", name="Edit message"),
        page.locator("button:has-text('Edit message')"),
        page.get_by_role("link", name="Edit message"),
    ]
    opened = False
    for sel in edit_btn_selectors:
        try:
            if await sel.count() > 0 and await sel.first.is_visible():
                await sel.first.click()
                await page.wait_for_timeout(5000)
                logger.info("DnD editor opened via 'Edit message'")
                opened = True
                break
        except Exception:
            continue
    if not opened:
        logger.warning("'Edit message' button not found — may already be in the editor")

    # Find the BEE iframe (retry up to 10s)
    bee_frame = None
    for _ in range(10):
        for frame in page.frames:
            if "getbee.io" in frame.url:
                bee_frame = frame
                break
        if bee_frame:
            break
        await page.wait_for_timeout(1000)

    if bee_frame:
        logger.info(f"BEE frame found: {bee_frame.url[:60]}")
    else:
        logger.warning("BEE iframe not found — URL updates may fail")

    # Swap each image in sequence
    success_count = 0
    for idx, (old_src, new_url) in enumerate(pairs):
        logger.info(
            f"Swapping slice {idx+1}/{len(pairs)}: "
            f"{old_src[:60]} → {new_url[:60]}"
        )
        ok = await _swap_single_image_in_bee(page, bee_frame, old_src, new_url, idx)
        if ok:
            success_count += 1
        # Re-acquire bee_frame in case it changed
        bee_frame = next(
            (f for f in page.frames if "getbee.io" in f.url), bee_frame
        )

    # Close editor once after all swaps
    await _close_dnd_editor(page)
    await page.wait_for_timeout(1000)
    logger.info(f"DnD editor closed. Swapped {success_count}/{len(pairs)} images.")
    return success_count, len(pairs)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def swap_campaign_slices(
    campaign_name: str,
    brand: str,
    new_image_urls: List[str],
    dry_run: bool = False,
    headless: bool = True,
    auto_confirm: bool = False,
) -> dict:
    """Fetch existing image srcs via API, pair with new URLs, swap in Braze DnD editor."""
    result: dict = {"success": False, "swapped": 0, "total": 0, "errors": []}

    # Step 1: Fetch existing campaign HTML via Braze REST API
    logger.info(f"Looking up API ID for campaign: {campaign_name}")
    api_id = find_campaign_api_id_by_name(campaign_name, brand)
    if not api_id:
        result["errors"].append(
            f"Campaign '{campaign_name}' not found via Braze API "
            f"(searched campaigns/list for brand {brand})"
        )
        return result

    logger.info(f"Campaign API ID: {api_id}")
    html = get_campaign_html(api_id, brand)
    if not html:
        result["errors"].append("Could not fetch campaign HTML via Braze API")
        return result

    existing_srcs = find_all_image_srcs(html)
    if not existing_srcs:
        result["errors"].append("No content images found in campaign HTML")
        return result

    # Step 2: Build positional pairs
    n = min(len(existing_srcs), len(new_image_urls))
    pairs = list(zip(existing_srcs[:n], new_image_urls[:n]))

    print("\n" + "=" * 60)
    print("SLICE SWAP SUMMARY")
    print("=" * 60)
    print(f"  Campaign:    {campaign_name}")
    print(f"  Brand:       {brand}")
    print(f"  Total slices found in HTML: {len(existing_srcs)}")
    print(f"  New URLs provided:          {len(new_image_urls)}")
    print(f"  Pairs to swap:              {n}")
    print()
    for i, (old, new) in enumerate(pairs):
        print(f"  [{i+1}] {old[:70]}")
        print(f"      → {new[:70]}")
    if len(existing_srcs) > len(new_image_urls):
        skipped = len(existing_srcs) - n
        print(f"\n  NOTE: {skipped} image(s) not swapped (no URL provided)")
    print("=" * 60)

    if dry_run:
        print("\nDRY RUN — no changes will be made.")
        result["success"] = True
        return result

    if not auto_confirm:
        confirm = input("\nProceed? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return result

    result["total"] = n

    # Step 3: Playwright session
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-save-password-bubble"],
            )
            context = await create_context_with_session(browser)
            await context.grant_permissions(["clipboard-read", "clipboard-write"])
            page = await context.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})

            await ensure_logged_in(page)
            await select_workspace(page, brand)

            # Open the existing draft campaign
            opened = await open_existing_campaign_editor(page, campaign_name, brand)
            if not opened:
                result["errors"].append(
                    f"Could not open campaign '{campaign_name}' in Braze"
                )
                await context.close()
                await browser.close()
                return result

            # Navigate to compose step if needed
            await navigate_to_compose_step(page)

            # Swap all slices in one DnD editor session
            swapped, total = await swap_all_images_in_dnd(page, pairs)
            result["swapped"] = swapped
            result["total"] = total

            if swapped < total:
                result["errors"].append(
                    f"Only {swapped}/{total} slices swapped — "
                    f"check debug screenshots in scripts/braze_automation/"
                )

            # Save as draft
            await save_as_draft(page, dry_run=False)
            await capture_screenshot(page, campaign_name)

            result["success"] = swapped > 0

            await context.close()
            await browser.close()

    except Exception as e:
        logger.exception("Playwright session failed")
        result["errors"].append(f"Playwright error: {e}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Swap image slices in an existing Braze designed-email draft."
    )
    parser.add_argument(
        "--campaign-name",
        required=True,
        help="Exact Braze campaign name",
    )
    parser.add_argument(
        "--brand",
        required=True,
        help="Brand code: CZ, HAV, BUR, etc.",
    )
    parser.add_argument(
        "--image-urls",
        nargs="+",
        required=True,
        help="New image URLs in order (top slice first). Must be Braze CDN URLs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pairs only — no browser or changes",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        default=True,
        help="Show browser window (default: headless)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    result = asyncio.run(
        swap_campaign_slices(
            campaign_name=args.campaign_name,
            brand=args.brand,
            new_image_urls=args.image_urls,
            dry_run=args.dry_run,
            headless=args.headless,
            auto_confirm=args.yes,
        )
    )

    print()
    if result["success"]:
        print(f"✓ Swapped {result['swapped']}/{result['total']} slices successfully.")
    else:
        print(
            f"✗ Slice swap failed or incomplete "
            f"({result['swapped']}/{result['total']})."
        )
    for e in result["errors"]:
        print(f"  Error: {e}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()

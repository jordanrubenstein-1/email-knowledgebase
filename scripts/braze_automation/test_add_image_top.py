#!/usr/bin/env python3
"""
Test script: duplicate a designed DnD campaign and add a new image row at the very top.

Usage:
    uv run python scripts/braze_automation/test_add_image_top.py
    uv run python scripts/braze_automation/test_add_image_top.py --no-headless
    uv run python scripts/braze_automation/test_add_image_top.py --dry-run
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, BRAZE_DASHBOARD_URL
from build_designed_campaign import (
    search_and_duplicate_email_campaign,
    _close_dnd_editor,
)
from build_push_campaign import (
    navigate_to_campaigns_list,
    set_campaign_name,
)
from build_pt_campaign import save_as_draft, get_campaign_url_from_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SOURCE_CAMPAIGN = "P_EM_2026_05_07_CZ_PC_D_Memorial_Day_Sale_Early_Access"
NEW_CAMPAIGN_NAME = "P_EM_2026_05_07_CZ_D_Memorial_Day_Sale_Early_Access_Image_Test"
BRAND = "CZ"
NEW_IMAGE_URL = "https://braze-images.com/appboy/communication/assets/image_assets/images/69fe42ec15a9760081a57b4b/original.png?1778270955"
LINK_URL = "https://www.the-citizenry.com"

DEBUG_DIR = PROJECT_ROOT / "scripts" / "braze_automation"


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _screenshot(page: Page, label: str) -> None:
    try:
        path = DEBUG_DIR / f"debug_add_image_{label}_{_ts()}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot: {path.name}")
    except Exception as e:
        logger.debug(f"Screenshot failed ({label}): {e}")


async def _open_dnd_editor(page: Page) -> bool:
    """Click 'Edit message' to enter the DnD editor."""
    for sel in [
        page.get_by_role("button", name="Edit message"),
        page.locator("button:has-text('Edit message')"),
        page.get_by_role("link", name="Edit message"),
    ]:
        try:
            if await sel.count() > 0 and await sel.first.is_visible():
                await sel.first.click()
                await page.wait_for_timeout(5000)
                logger.info("Clicked 'Edit message' — DnD editor loading")
                return True
        except Exception:
            continue
    logger.warning("'Edit message' button not found")
    return False


async def _get_bee_frame(page: Page):
    """Return the BEE editor iframe, or None."""
    for frame in page.frames:
        if "getbee.io" in frame.url:
            logger.info(f"BEE frame: {frame.url[:80]}")
            return frame
    return None


async def _dump_bee_dom(bee_frame, label: str = "") -> None:
    """Log BEE frame DOM info for debugging selector discovery."""
    try:
        info = await bee_frame.evaluate("""() => {
            const rows = Array.from(document.querySelectorAll('[class*="bee-row"], [data-bee-row], .bee-row, [id*="row"]')).slice(0, 5).map(el => ({
                tag: el.tagName,
                id: el.id || '',
                cls: el.className.slice(0, 80),
                dataAttrs: Object.fromEntries(
                    Array.from(el.attributes)
                        .filter(a => a.name.startsWith('data-'))
                        .map(a => [a.name, a.value.slice(0, 40)])
                ),
            }));
            const addBtns = Array.from(document.querySelectorAll(
                '[class*="add"], [aria-label*="add" i], [title*="add" i], [class*="insert"], button'
            )).slice(0, 20).map(el => ({
                tag: el.tagName,
                text: (el.textContent || '').trim().slice(0, 30),
                cls: el.className.slice(0, 60),
                ariaLabel: el.getAttribute('aria-label') || '',
                title: el.getAttribute('title') || '',
            }));
            const allCls = Array.from(new Set(
                Array.from(document.querySelectorAll('*'))
                    .flatMap(el => Array.from(el.classList))
                    .filter(c => c.includes('row') || c.includes('add') || c.includes('block') || c.includes('content'))
            )).slice(0, 40);
            return {rows, addBtns, allCls};
        }""")
        logger.info(f"BEE DOM [{label}] rows: {len(info['rows'])}, addBtns: {len(info['addBtns'])}")
        for r in info["rows"]:
            logger.info(f"  ROW {r['tag']} id={r['id']!r} cls={r['cls']!r} data={r['dataAttrs']}")
        for b in info["addBtns"][:10]:
            logger.info(f"  BTN {b['tag']} text={b['text']!r} cls={b['cls']!r} aria={b['ariaLabel']!r}")
        logger.info(f"  Class tokens: {info['allCls']}")
    except Exception as e:
        logger.debug(f"BEE DOM dump failed: {e}")


async def _dump_all_bee_inputs(bee_frame, label: str = "") -> None:
    """Log every input in BEE frame with full details."""
    try:
        inputs = await bee_frame.evaluate("""() => {
            return Array.from(document.querySelectorAll('input')).map((inp, i) => ({
                idx: i,
                type: inp.type || '',
                value: (inp.value || '').slice(0, 100),
                placeholder: inp.placeholder || '',
                id: inp.id || '',
                name: inp.name || '',
                ariaLabel: inp.getAttribute('aria-label') || '',
                cls: inp.className.slice(0, 60),
                labelText: (() => {
                    const label = document.querySelector(`label[for="${inp.id}"]`);
                    if (label) return label.textContent.trim().slice(0, 40);
                    const parentLabel = inp.closest('label');
                    if (parentLabel) return parentLabel.textContent.trim().slice(0, 40);
                    // Look for preceding sibling text
                    const parent = inp.parentElement;
                    if (parent) return parent.textContent.trim().slice(0, 40);
                    return '';
                })(),
            }));
        }""")
        logger.info(f"BEE inputs [{label}] ({len(inputs)}):")
        for inp in inputs:
            logger.info(f"  [{inp['idx']}] type={inp['type']!r} val={inp['value']!r} ph={inp['placeholder']!r} label={inp['labelText']!r}")
    except Exception as e:
        logger.debug(f"BEE inputs dump failed: {e}")


async def _drag_image_block_to_top(bee_frame, page: Page) -> bool:
    """
    Drag the 'Image' content block from the CONTENT > MEDIA sidebar panel
    and drop it at the very top of the email canvas (above row 1).

    BEE layout:
      Right sidebar → CONTENT tab → MEDIA section → Image draggable
      Canvas → rows; drop at y = row1.top + a few pixels to insert above
    """
    # Find the Image draggable in the MEDIA section of the Content sidebar
    source_selectors = [
        '[aria-label="Image"][class*="sidebar-draggable"]',
        '[aria-label="Image"].sidebar-draggable--cs',
        '[class*="sidebar-draggable"][aria-label="Image"]',
        '[class*="SidebarDraggable"][aria-label="Image"]',
    ]
    source_el = None
    source_box = None
    for sel in source_selectors:
        try:
            el = bee_frame.locator(sel)
            cnt = await el.count()
            if cnt > 0:
                box = await el.first.bounding_box()
                if box:
                    source_el = el.first
                    source_box = box
                    logger.info(f"Image draggable found: {sel!r} box={box}")
                    break
        except Exception as e:
            logger.debug(f"Source selector {sel!r}: {e}")

    if source_box is None:
        logger.error("Could not find Image draggable in CONTENT sidebar")
        return False

    # Find the first row to get a drop target (drop just above it)
    target_box = None
    for sel in ["[aria-label*='row 1 out of']", "[class*='row-container-outer--first']"]:
        try:
            el = bee_frame.locator(sel)
            if await el.count() > 0:
                box = await el.first.bounding_box()
                if box:
                    target_box = box
                    logger.info(f"First row box: {box}")
                    break
        except Exception:
            continue

    if target_box is None:
        logger.error("Could not find first row for drop target")
        return False

    # Perform the drag
    src_x = source_box["x"] + source_box["width"] / 2
    src_y = source_box["y"] + source_box["height"] / 2
    # Drop at the very top of the first row to insert ABOVE it
    drop_x = target_box["x"] + target_box["width"] / 2
    drop_y = target_box["y"] + 8  # a few pixels from the top edge

    logger.info(f"Dragging Image from ({src_x:.0f}, {src_y:.0f}) → ({drop_x:.0f}, {drop_y:.0f})")

    try:
        # bounding_box() returns viewport coords even for iframe elements —
        # use page.mouse (not bee_frame.mouse, which doesn't exist)
        await page.mouse.move(src_x, src_y)
        await page.wait_for_timeout(300)
        await page.mouse.down()
        await page.wait_for_timeout(300)
        # Move slowly toward the target so BEE detects the drag
        steps = 20
        for i in range(1, steps + 1):
            ix = src_x + (drop_x - src_x) * i / steps
            iy = src_y + (drop_y - src_y) * i / steps
            await page.mouse.move(ix, iy)
            await page.wait_for_timeout(40)
        await page.wait_for_timeout(800)
        await page.mouse.up()
        await page.wait_for_timeout(2500)
        logger.info("Drag complete")
        return True
    except Exception as e:
        logger.error(f"Drag failed: {e}")
        return False


async def _click_first_row_and_get_add_above(bee_frame, page: Page) -> bool:
    """
    Add a new row above row 1 in the BEE canvas.

    BEE v3 shows "+" buttons between rows when hovering. The strategy:
    1. Find the first row's bounding box
    2. Hover at the very top edge of the first row (y = row.top + 2)
       — BEE renders an add-before-first-row "+" there
    3. Click the "+" to insert a new blank row above row 1
    4. If that fails, try selecting the row and looking for row-action buttons
    """
    # Find the first row
    first_row_el = None
    first_row_box = None
    row_sel_candidates = [
        "[aria-label*='row 1 out of']",
        "[class*='row-container-outer--first']",
        "[class*='StageRow_row']:first-of-type",
    ]
    for sel in row_sel_candidates:
        try:
            el = bee_frame.locator(sel)
            if await el.count() > 0:
                box = await el.first.bounding_box()
                if box:
                    first_row_el = el.first
                    first_row_box = box
                    logger.info(f"First row box via {sel!r}: {box}")
                    break
        except Exception as e:
            logger.debug(f"Row box failed ({sel!r}): {e}")

    if first_row_box is None:
        logger.warning("Could not get first row bounding box")
        return False

    cx = first_row_box["x"] + first_row_box["width"] / 2
    top_y = first_row_box["y"]

    # -- Strategy A: hover at the very top edge of row 1 to reveal "add above" --
    # BEE renders a "+" button just above row 1 when hovering near the top border.
    # We need to move to top_y - 5 first (above the row), then down to top_y + 2.
    try:
        await bee_frame.mouse.move(cx, top_y - 10)
        await page.wait_for_timeout(300)
        await bee_frame.mouse.move(cx, top_y + 2)
        await page.wait_for_timeout(500)
        logger.info(f"Hovering at top edge of first row: ({cx:.0f}, {top_y + 2:.0f})")
    except Exception as e:
        logger.debug(f"Top-edge hover failed: {e}")

    # Dump ALL elements (including hidden) near the first row's labels area
    try:
        all_els = await bee_frame.evaluate(f"""() => {{
            // Collect everything in the row-labels area and nearby
            const results = [];
            const selectors = [
                '[class*="row-labels"]',
                '[class*="StageRow_rowLabels"]',
                '[class*="row-add"]',
                '[class*="addRow"]',
                '[class*="add-row"]',
                '[class*="row-action"]',
            ];
            for (const sel of selectors) {{
                document.querySelectorAll(sel).forEach(el => {{
                    const rect = el.getBoundingClientRect();
                    const children = Array.from(el.querySelectorAll('button, [role="button"]')).map(c => ({{
                        tag: c.tagName,
                        text: (c.textContent||'').trim().slice(0,30),
                        aria: c.getAttribute('aria-label')||'',
                        cls: c.className.slice(0,60),
                        rect: c.getBoundingClientRect(),
                        opacity: window.getComputedStyle(c).opacity,
                    }}));
                    results.push({{
                        sel,
                        cls: el.className.slice(0,80),
                        rect: {{x: rect.x, y: rect.y, w: rect.width, h: rect.height}},
                        childCount: children.length,
                        children,
                    }});
                }});
            }}
            return results;
        }}""")
        logger.info(f"Row-label elements ({len(all_els)}):")
        for el in all_els[:5]:
            logger.info(f"  sel={el['sel']!r} rect={el['rect']} children={el['childCount']}")
            for c in el.get("children", [])[:5]:
                logger.info(f"    {c['tag']} aria={c['aria']!r} cls={c['cls'][:40]!r} opacity={c['opacity']!r}")
    except Exception as e:
        logger.debug(f"Row-labels dump failed: {e}")

    # -- Look for "+" buttons anywhere in the BEE frame, including those
    #    with opacity:0 (hidden until hover) --
    try:
        all_plus = await bee_frame.evaluate(f"""() => {{
            const topY = {top_y};
            const all = Array.from(document.querySelectorAll('*'));
            return all.filter(el => {{
                const t = (el.textContent||'').trim();
                const aria = el.getAttribute('aria-label') || '';
                const cls = el.className || '';
                return (
                    t === '+' ||
                    aria.toLowerCase().includes('add') ||
                    cls.includes('add') ||
                    cls.includes('plus') ||
                    cls.includes('insert')
                );
            }}).slice(0, 20).map(el => {{
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {{
                    tag: el.tagName,
                    text: (el.textContent||'').trim().slice(0,20),
                    aria: el.getAttribute('aria-label')||'',
                    cls: el.className.slice(0,60),
                    opacity: style.opacity,
                    display: style.display,
                    rect: {{x: rect.x, y: rect.y, w: rect.width, h: rect.height}},
                }};
            }});
        }}""")
        logger.info(f"Elements with add/plus/insert ({len(all_plus)}):")
        for el in all_plus:
            logger.info(f"  {el['tag']} text={el['text']!r} aria={el['aria']!r} cls={el['cls'][:40]!r} opacity={el['opacity']!r} rect={el['rect']}")
    except Exception as e:
        logger.debug(f"Plus-element dump failed: {e}")

    # -- Strategy B: click on the first row to SELECT it, then look for
    #    row action buttons that become visible after selection --
    try:
        await first_row_el.click()
        await page.wait_for_timeout(1000)
        logger.info("Clicked first row to select it")
    except Exception as e:
        logger.debug(f"First row click failed: {e}")

    # Dump buttons again after selection
    try:
        post_click_btns = await bee_frame.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, [role="button"]')).map(el => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.textContent||'').trim().slice(0,30),
                    aria: el.getAttribute('aria-label')||'',
                    cls: el.className.slice(0,80),
                    opacity: style.opacity,
                    display: style.display,
                    rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                };
            }).filter(b => b.opacity > 0 || b.aria.includes('add') || b.aria.includes('row'));
        }""")
        logger.info(f"Buttons after row selection ({len(post_click_btns)}):")
        for b in post_click_btns[:20]:
            logger.info(f"  {b['tag']} aria={b['aria']!r} opacity={b['opacity']!r} rect={b['rect']}")
    except Exception as e:
        logger.debug(f"Post-selection button dump: {e}")

    # Try aria-label patterns
    add_above_selectors = [
        '[aria-label*="Add row above" i]',
        '[aria-label*="add above" i]',
        '[aria-label*="insert above" i]',
        '[aria-label*="row above" i]',
        '[aria-label*="before" i]',
        '[title*="Add row above" i]',
        '[title*="add above" i]',
        '[class*="row-add-above"]',
        '[class*="addRowAbove"]',
        '[class*="add_above"]',
        '[class*="icon-add-above"]',
        '[class*="add-above"]',
        # Try data-qa
        '[data-qa*="add-above"]',
        '[data-qa*="row-add"]',
    ]
    for sel in add_above_selectors:
        try:
            btn = bee_frame.locator(sel)
            cnt = await btn.count()
            if cnt > 0:
                logger.info(f"Add-row-above button found ({cnt}): {sel!r}")
                await btn.first.click()
                await page.wait_for_timeout(2000)
                return True
        except Exception as e:
            logger.debug(f"Add-above selector {sel!r}: {e}")

    # -- Strategy C: click at the "+" position we saw in the screenshot --
    # The "+" appears on the right edge of the first row. Try clicking there.
    try:
        right_edge_x = first_row_box["x"] + first_row_box["width"] - 10
        mid_y = first_row_box["y"] + first_row_box["height"] / 2
        logger.info(f"Clicking right edge of first row: ({right_edge_x:.0f}, {mid_y:.0f})")
        await bee_frame.mouse.click(right_edge_x, mid_y)
        await page.wait_for_timeout(2000)

        # Check if a row was added (row count should increase)
        new_count = await bee_frame.locator("[aria-label*='out of']").count()
        logger.info(f"Row count after right-edge click: {new_count}")
        if new_count > 4:
            logger.info("Row count increased — new row added!")
            return True
    except Exception as e:
        logger.debug(f"Right-edge click failed: {e}")

    # -- Strategy D: hover at top-left corner of first row (near drag handle area) --
    # The row action toolbar (add above/below, delete) in BEE often appears in the
    # row-labels div on the LEFT side. Try hovering there.
    try:
        left_x = first_row_box["x"] + 15
        label_y = first_row_box["y"] + 15
        await bee_frame.mouse.move(left_x, label_y)
        await page.wait_for_timeout(800)
        logger.info(f"Hovering at row label area: ({left_x:.0f}, {label_y:.0f})")

        # Try to find any newly-visible "add" button
        add_btn = bee_frame.locator('[aria-label*="add" i], [aria-label*="above" i], [title*="add" i]')
        cnt = await add_btn.count()
        if cnt > 0:
            logger.info(f"Found add button after label hover: {cnt}")
            await add_btn.first.click()
            await page.wait_for_timeout(2000)
            return True
    except Exception as e:
        logger.debug(f"Label hover failed: {e}")

    logger.warning("All add-row-above strategies failed")
    return False


async def add_image_row_at_top(page: Page, image_url: str, link_url: str) -> bool:
    """
    Add a new image row at the very top of the BEE DnD editor.

    Strategy:
    1. Click the first row to select it, revealing row action toolbar
    2. Click "Add row above" from the toolbar → new blank row inserted above
    3. Click the image placeholder in the new row
    4. Set image URL via URL input in properties panel
    5. Set link URL via the Action section's link input
    """
    await _screenshot(page, "before_add_row")

    bee_frame = await _get_bee_frame(page)
    if bee_frame is None:
        logger.error("BEE iframe not found — cannot add row")
        return False

    await _dump_bee_dom(bee_frame, "initial")

    # ------------------------------------------------------------------
    # Step 1: Drag Image block from CONTENT > MEDIA sidebar to top of canvas
    # ------------------------------------------------------------------
    added = await _drag_image_block_to_top(bee_frame, page)
    await _screenshot(page, "after_drag_attempt")

    # ------------------------------------------------------------------
    # Step 2: Click inside the newly-added image block to open IMAGE PROPERTIES.
    # After the drag, BEE inserts a new empty image block at the top. It has
    # no <img src> yet — it shows a "Use Browse button to add an image" hint.
    # We click at the drop location (where we released the mouse) to select it.
    # ------------------------------------------------------------------
    await _screenshot(page, "after_add_row")

    # Retrieve the drop coordinates that _drag_image_block_to_top computed.
    # We re-compute here using the same first-row selector.
    drop_click_x, drop_click_y = None, None
    try:
        first_row = bee_frame.locator("[aria-label*='row 1 out of']")
        if await first_row.count() == 0:
            first_row = bee_frame.locator("[class*='row-container-outer']:first-of-type")
        box = await first_row.first.bounding_box()
        if box:
            drop_click_x = box["x"] + box["width"] / 2
            # The new block was added AT the top of row 1 (now row 2).
            # The new row occupies roughly y=75 to ~75+200. Click midpoint.
            drop_click_y = box["y"] + 50  # slightly below the very top
            logger.info(f"Clicking new image block at ({drop_click_x:.0f}, {drop_click_y:.0f})")
            await page.mouse.click(drop_click_x, drop_click_y)
            await page.wait_for_timeout(2000)
    except Exception as e:
        logger.debug(f"Drop-position click failed: {e}")

    # Fallback: try clicking the first content-labels--image area (the new block)
    if drop_click_x is None:
        try:
            el = bee_frame.locator("[class*='content-labels--image']").first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(2000)
                logger.info("Clicked first content-labels--image")
        except Exception as e:
            logger.debug(f"content-labels click failed: {e}")

    await _screenshot(page, "after_img_click")

    # ------------------------------------------------------------------
    # Step 3: Set image URL in the properties panel
    #
    # From DOM inspection of BEE image properties (input layout):
    #   text[0]  label='URL'        → image source URL  ← SET THIS
    #   text[1]  label='Alt text'   → alt attribute
    #   text[2]  label='Image link' → clickable link URL ← SET THIS
    #   text[3]  label='URL' (2nd)  → action URL (already has value from original)
    #   text[4+] → background color, link color, font, etc. (global settings)
    # ------------------------------------------------------------------
    bee_frame = await _get_bee_frame(page)
    if bee_frame is None:
        logger.error("BEE frame gone")
        return False

    await _dump_all_bee_inputs(bee_frame, "properties_panel_open")

    image_url_set = False
    image_url_escaped = image_url.replace("'", "\\'")
    link_url_escaped = link_url.replace("'", "\\'")

    try:
        await page.wait_for_timeout(1000)
        all_text = bee_frame.locator("input[type='text']")
        count = await all_text.count()
        logger.info(f"Text inputs in panel: {count}")
        for i in range(min(count, 8)):
            val = await all_text.nth(i).input_value()
            logger.info(f"  input[{i}] val={val[:80]!r}")

        # text[0] = image source URL
        if count >= 1:
            url_inp = all_text.nth(0)
            await url_inp.click()
            await url_inp.fill(image_url)
            await url_inp.press("Tab")
            await page.wait_for_timeout(500)
            logger.info("Image URL set on text[0]")
            image_url_set = True
    except Exception as e:
        logger.debug(f"Image URL fill failed: {e}")

    if not image_url_set:
        try:
            result = await bee_frame.evaluate(f"""() => {{
                const inp = document.querySelector('input[type="text"]');
                if (!inp) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, '{image_url_escaped}');
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}""")
            if result:
                image_url_set = True
                logger.info("Image URL set via JS native setter")
        except Exception as e:
            logger.debug(f"JS image URL setter failed: {e}")

    # ------------------------------------------------------------------
    # Step 4: Set link URL on the "Image link" field (text[2], label='Image link')
    # ------------------------------------------------------------------
    await _dump_all_bee_inputs(bee_frame, "before_link_set")
    link_set = False

    try:
        all_text = bee_frame.locator("input[type='text']")
        count = await all_text.count()
        # text[2] is "Image link" — but confirm by checking it's empty or already a URL
        if count >= 3:
            link_inp = all_text.nth(2)
            link_val = await link_inp.input_value()
            logger.info(f"text[2] current val: {link_val!r}")
            await link_inp.click()
            await link_inp.fill(link_url)
            await link_inp.press("Tab")
            await page.wait_for_timeout(500)
            logger.info(f"Link URL set on text[2] (Image link field)")
            link_set = True
    except Exception as e:
        logger.debug(f"Link URL on text[2] failed: {e}")

    if not link_set:
        # Fallback via JS: find the "Image link" input by label proximity
        try:
            result = await bee_frame.evaluate(f"""() => {{
                const all = Array.from(document.querySelectorAll('input[type="text"]'));
                const imgLink = all.find(inp => {{
                    const p = inp.parentElement;
                    return p && p.textContent.toLowerCase().includes('image link');
                }});
                const target = imgLink || all[2];
                if (!target) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(target, '{link_url_escaped}');
                target.dispatchEvent(new Event('input', {{bubbles: true}}));
                target.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}""")
            if result:
                link_set = True
                logger.info("Link URL set via JS fallback (Image link field)")
        except Exception as e:
            logger.debug(f"JS link fallback failed: {e}")

    await _screenshot(page, "after_url_set")
    logger.info(f"Image URL set: {image_url_set}, Link URL set: {link_set}")

    return image_url_set


async def run(headless: bool = True, dry_run: bool = False) -> bool:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await create_context_with_session(browser)
        page = await context.new_page()

        try:
            # Navigate to campaigns list
            logger.info("Navigating to campaigns list...")
            await navigate_to_campaigns_list(page, brand=BRAND)
            await page.wait_for_timeout(3000)

            # Duplicate the source campaign
            logger.info(f"Duplicating '{SOURCE_CAMPAIGN}'...")
            duped = await search_and_duplicate_email_campaign(page, SOURCE_CAMPAIGN, BRAND)
            if not duped:
                logger.error("Failed to duplicate campaign")
                return False

            await page.wait_for_timeout(3000)
            await _screenshot(page, "after_duplicate")

            # Rename the duplicate
            logger.info(f"Renaming to '{NEW_CAMPAIGN_NAME}'...")
            renamed = await set_campaign_name(page, NEW_CAMPAIGN_NAME)
            if not renamed:
                logger.warning("Rename may have failed — continuing")

            await page.wait_for_timeout(2000)
            await _screenshot(page, "after_rename")

            if dry_run:
                logger.info("DRY RUN — stopping before DnD edits")
                return True

            # Open the DnD editor
            logger.info("Opening DnD editor...")
            opened = await _open_dnd_editor(page)
            if not opened:
                logger.warning("Could not confirm editor opened — proceeding anyway")

            await page.wait_for_timeout(3000)
            await _screenshot(page, "editor_open")

            # Add new image row at top
            logger.info("Adding image row at top...")
            added = await add_image_row_at_top(page, NEW_IMAGE_URL, LINK_URL)

            if not added:
                logger.error("Failed to add image row — check debug screenshots")

            # Close editor
            await _close_dnd_editor(page)
            await page.wait_for_timeout(2000)
            await _screenshot(page, "after_close_editor")

            # Save as draft
            logger.info("Saving as draft...")
            saved = await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)

            campaign_url = get_campaign_url_from_page(page.url)
            logger.info(f"Done. Campaign URL: {campaign_url or page.url}")
            await _screenshot(page, "final")

            return saved or added

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await _screenshot(page, "error")
            return False
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Test adding a new image row at top of DnD campaign")
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True)
    parser.add_argument("--dry-run", action="store_true", help="Duplicate + rename only, no DnD edits")
    args = parser.parse_args()

    success = asyncio.run(run(headless=args.headless, dry_run=args.dry_run))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

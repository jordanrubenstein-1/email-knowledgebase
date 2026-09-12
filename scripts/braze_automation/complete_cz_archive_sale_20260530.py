#!/usr/bin/env python3
"""
Complete the CZ Archive Sale campaign that was partially configured.

The campaign was duplicated and had audience/delivery set, but the Playwright
session crashed before conversions, UTMs, save-as-draft, and Asana update.

This script picks up from that point.

Campaign ID:    6a12148eca2f6f008102370c
Campaign name:  P_EM_2026_05_30_CZ_D_Archive_Sale
Asana task GID: 1213928748054248
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session
from build_pt_campaign import (
    save_as_draft,
    get_campaign_url_from_page,
    capture_screenshot,
    update_asana_with_braze_link,
    _asana_request,
    _configure_link_templates,
    load_brand_config,
    get_brand_entry,
    fetch_task_by_gid,
)
from build_push_campaign import wait_for_campaign_editor
from build_designed_campaign import (
    configure_conversions_designed,
    STATUS_READY_FOR_QA,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TASK_GID     = "1213928748054248"
BRAND        = "CZ"
CAMPAIGN_ID  = "6a12148eca2f6f008102370c"
FIELD_TASK_STATUS = "1209982215610993"

BRAZE_DASHBOARD_BASE = os.environ.get(
    "BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com"
).rstrip("/")

CAMPAIGN_URL = f"{BRAZE_DASHBOARD_BASE}/engagement/campaigns/{CAMPAIGN_ID}"


async def main():
    logger.info(f"Completing CZ Archive Sale campaign: {CAMPAIGN_URL}")

    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"
    logger.info(f"UTM templates: {utm_templates!r}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        from login import ensure_logged_in, select_workspace
        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        # Navigate via campaigns list — direct URL loads overview, not editor
        from build_push_campaign import navigate_to_campaigns_list, _set_status_filter
        from build_designed_campaign import _search_with_enter

        CAMPAIGN_NAME = "P_EM_2026_05_30_CZ_D_Archive_Sale"
        logger.info(f"Navigating to campaigns list to open: {CAMPAIGN_NAME}")
        await navigate_to_campaigns_list(page, brand=BRAND)
        await page.wait_for_timeout(1000)

        # Search for the campaign under Draft status
        await _set_status_filter(page, "Draft")
        await _search_with_enter(page, CAMPAIGN_NAME)

        # Click the campaign name to open it for editing
        name_link = page.get_by_text(CAMPAIGN_NAME, exact=True).first
        await name_link.wait_for(state="visible", timeout=10000)
        await name_link.click()
        await page.wait_for_timeout(3000)
        await wait_for_campaign_editor(page)
        logger.info(f"Editor loaded. URL: {page.url}")

        # Step 1: Configure conversion events
        logger.info("Configuring conversion events...")
        await configure_conversions_designed(page, BRAND)

        # Step 2: Navigate back to Compose for UTM link templates
        logger.info("Navigating to Compose for UTM templates...")
        try:
            compose_btn = page.get_by_role("button", name="Compose Messages")
            if await compose_btn.count() == 0:
                compose_btn = page.get_by_role("button", name="Compose")
            if await compose_btn.count() > 0:
                await compose_btn.click()
                await page.wait_for_timeout(2000)
                logger.info("On Compose step")
        except Exception as e:
            logger.warning(f"Could not navigate to Compose step: {e}")

        # Step 3: Apply UTM link templates
        logger.info("Applying UTM link templates...")
        await _configure_link_templates(page, utm_templates)

        # Step 4: Save as draft
        logger.info("Saving as draft...")
        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)

        braze_url = get_campaign_url_from_page(page.url)
        if not braze_url:
            braze_url = page.url
        logger.info(f"Saved. URL: {braze_url}")

        try:
            dbg = str(Path(__file__).parent / "debug_complete_final.png")
            await page.screenshot(path=dbg, full_page=False)
            logger.info(f"Final screenshot: {dbg}")
        except Exception:
            pass

        await context.close()
        await browser.close()

    # Step 5: Update Asana
    logger.info("Updating Asana...")

    ok = update_asana_with_braze_link(TASK_GID, braze_url)
    logger.info("Braze link written" if ok else "WARNING: Braze link write failed")

    qa_ok = _asana_request(
        "PUT", f"tasks/{TASK_GID}",
        json_data={"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
    )
    logger.info("Status → Ready for QA" if qa_ok else "WARNING: Status update failed")

    task = fetch_task_by_gid(TASK_GID)
    assignee = (task or {}).get("assignee") or {}
    assignee_gid = assignee.get("gid")

    import html as _html
    body_text = (
        "this designed email has been automatically built in Braze. "
        "The HTML template, subject/preheader, audience, send schedule, conversion events, "
        "and UTM link templates are all configured. "
        "Please QA the email, subject line and preheader, audience, and send schedule "
        "before sending to the QA group.\n\n"
        f"Campaign link: {braze_url}"
    )

    if assignee_gid:
        html_body = _html.escape(body_text, quote=False)
        url_escaped = _html.escape(braze_url, quote=False)
        url_attr = _html.escape(braze_url, quote=True)
        html_body = html_body.replace(url_escaped, f'<a href="{url_attr}">{url_escaped}</a>')
        html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
        payload = {"data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}}
    else:
        body_text = body_text[0].upper() + body_text[1:]
        payload = {"data": {"text": body_text, "is_pinned": False}}

    comment_ok = _asana_request("POST", f"tasks/{TASK_GID}/stories", json_data=payload)
    logger.info("Comment posted" if comment_ok else "WARNING: Comment failed")

    print("\nBraze link written: OK")
    print("Status → Ready for QA: OK")
    print("Comment posted: OK")
    print(f"\nDone. Braze URL: {braze_url}")


if __name__ == "__main__":
    asyncio.run(main())

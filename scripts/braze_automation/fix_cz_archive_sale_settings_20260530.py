#!/usr/bin/env python3
"""
One-off fix: configure CZ Archive Sale campaign settings (2026-05-30).

The campaign was already created in Braze with the correct HTML/CSS body,
but is missing: conversion events, target audience (Full File, no control group,
Variant 1=100%), delivery schedule (Intelligent Timing 4PM fallback), and UTM
link templates.

This script opens the existing campaign and applies all missing settings, then
updates Asana: writes the Braze link, sets status → Ready for QA, and posts a
comment.

Asana task GID:   1213928748054248
Braze campaign ID: 6a120bd5d61c2a0084d392ee
Campaign name:    P_EM_2026_05_30_CZ_D_Archive_Sale
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
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
    _get_text_value,
    fetch_task_by_gid,
)
from build_push_campaign import (
    wait_for_campaign_editor,
    set_campaign_name,
)
from build_designed_campaign import (
    configure_audience_designed,
    configure_conversions_designed,
    configure_delivery_designed,
    resolve_send_time_designed,
    STATUS_READY_FOR_QA,
    FIELD_REF_BRAZE_CAMPAIGN,
)
from build_pt_campaign import (
    load_brand_config,
    get_brand_entry,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TASK_GID       = "1213928748054248"
BRAND          = "CZ"
CAMPAIGN_ID    = "6a120bd5d61c2a0084d392ee"
CAMPAIGN_NAME  = "P_EM_2026_05_30_CZ_D_Archive_Sale"
SEND_DATE      = "2026-05-30"
TASK_NAME      = "Archive Sale"
SEND_TIME_RAW  = "4 PM"
SEGMENT_TYPE   = "full_file"

BRAZE_DASHBOARD_BASE = os.environ.get(
    "BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com"
).rstrip("/")

FIELD_TASK_STATUS = "1209982215610993"

CAMPAIGN_EDIT_URL = (
    f"{BRAZE_DASHBOARD_BASE}/engagement/campaigns/{CAMPAIGN_ID}"
)


async def main():
    logger.info("=== CZ Archive Sale settings fix ===")
    logger.info(f"  Campaign ID:  {CAMPAIGN_ID}")
    logger.info(f"  Campaign URL: {CAMPAIGN_EDIT_URL}")

    send_time_config = resolve_send_time_designed(TASK_NAME, SEND_DATE, SEND_TIME_RAW)
    logger.info(f"  Send time config: {send_time_config}")

    # Load UTM templates for CZ
    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"
    logger.info(f"  UTM templates: {utm_templates!r}")

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

        # Navigate directly to existing campaign
        logger.info(f"Navigating to campaign: {CAMPAIGN_EDIT_URL}")
        await page.goto(CAMPAIGN_EDIT_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Wait for campaign editor to be ready
        await wait_for_campaign_editor(page)
        logger.info(f"Campaign editor loaded. Current URL: {page.url}")

        # Screenshot initial state
        try:
            dbg = str(Path(__file__).parent / "debug_fix_initial.png")
            await page.screenshot(path=dbg, full_page=False)
            logger.info(f"Initial screenshot: {dbg}")
        except Exception:
            pass

        # Step 1: Rename campaign if needed
        logger.info(f"Setting campaign name: {CAMPAIGN_NAME}")
        await set_campaign_name(page, CAMPAIGN_NAME)

        # Step 2: Configure audience (Full File, control group=0%, Variant 1=100%)
        logger.info("Configuring target audience...")
        await configure_audience_designed(
            page,
            desired_segment_type=SEGMENT_TYPE,
            ref_segment_type=None,  # force reconfigure
            brand=BRAND,
            hav_variant=None,
        )

        # Step 3: Configure delivery (Intelligent Timing, 4PM fallback, launch 2026-05-30)
        logger.info("Configuring delivery schedule...")
        await configure_delivery_designed(page, send_time_config, SEND_DATE)

        # Step 4: Configure conversion events
        logger.info("Configuring conversion events...")
        await configure_conversions_designed(page, BRAND)

        # Step 5: Apply UTM link templates
        # Navigate back to Compose to access Link Management
        logger.info("Applying UTM link templates...")
        try:
            compose_btn = page.get_by_role("button", name="Compose Message")
            if await compose_btn.count() == 0:
                compose_btn = page.get_by_role("button", name="Compose")
            if await compose_btn.count() > 0:
                await compose_btn.click()
                await page.wait_for_timeout(2000)
                logger.info("Navigated back to Compose step for UTM configuration")
        except Exception as e:
            logger.warning(f"Could not navigate to Compose step: {e}")

        await _configure_link_templates(page, utm_templates)

        # Step 6: Save as draft
        logger.info("Saving campaign as draft...")
        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)

        braze_url = get_campaign_url_from_page(page.url)
        if not braze_url:
            braze_url = page.url
        logger.info(f"Campaign saved. URL: {braze_url}")

        # Screenshot final state
        try:
            final_dbg = str(Path(__file__).parent / "debug_fix_final.png")
            await page.screenshot(path=final_dbg, full_page=False)
            logger.info(f"Final screenshot: {final_dbg}")
        except Exception:
            pass

        await context.close()
        await browser.close()

    # Step 7: Update Asana
    logger.info("Updating Asana task...")

    # Write Braze link
    ok = update_asana_with_braze_link(TASK_GID, braze_url)
    if ok:
        logger.info("Braze link written to Asana")
    else:
        logger.warning("Failed to write Braze link to Asana")

    # Change status → Ready for QA
    qa_payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
    qa_ok = _asana_request("PUT", f"tasks/{TASK_GID}", json_data=qa_payload)
    if qa_ok:
        logger.info("Asana status → Ready for QA")
    else:
        logger.warning("Failed to update Asana status")

    # Post comment (with assignee mention if available)
    task = fetch_task_by_gid(TASK_GID)
    assignee = (task or {}).get("assignee") or {}
    assignee_gid = assignee.get("gid")

    body_text = (
        "this designed email has been automatically built in Braze. "
        "The HTML template, subject/preheader, audience, send schedule, conversion events, "
        "and UTM link templates are all configured. "
        "Please QA the email, subject line and preheader, audience, and send schedule "
        "before sending to the QA group.\n\n"
        f"Campaign link: {braze_url}"
    )

    import html as _html
    if assignee_gid:
        html_body = _html.escape(body_text, quote=False)
        _url_text = _html.escape(braze_url, quote=False)
        _url_attr = _html.escape(braze_url, quote=True)
        html_body = html_body.replace(
            _url_text,
            f'<a href="{_url_attr}">{_url_text}</a>',
        )
        html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
        payload = {"data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}}
    else:
        body_text = body_text[0].upper() + body_text[1:]
        payload = {"data": {"text": body_text, "is_pinned": False}}

    comment_ok = _asana_request("POST", f"tasks/{TASK_GID}/stories", json_data=payload)
    if comment_ok:
        logger.info("Comment posted on Asana task")
    else:
        logger.warning("Failed to post Asana comment")

    print("\n" + "=" * 60)
    print("STATUS → Ready for QA: OK")
    print(f"Braze URL: {braze_url}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
One-off: Build CZ Archive Sale (2026-05-30) as an HTML/CSS Braze campaign.

This uses the HTML/CSS code editor approach — NOT drag-and-drop — which is the
correct method for CZ designed emails (6/9 forward workflow, applied here as a
one-off for this pre-6/9 campaign).

Steps:
  1. Archive the old (incorrectly DnD-built) campaign via Braze API
  2. Create a NEW HTML/CSS campaign via Create Campaign → Email → HTML code editor
  3. Set campaign name, subject, preheader
  4. Inject pre-built HTML via Monaco editor
  5. Apply UTM link templates
  6. Configure Target Audience: CZ Full File, control 0%, Variant 1 = 100%
  7. Configure Delivery: Intelligent Timing, 2026-05-30, 4:00 PM fallback
  8. Configure Conversion Events: CZ standard (A–D, 3-day window)
  9. Save as draft
 10. Update Asana: Braze link → Ready for QA → comment

Campaign name:  P_EM_2026_05_30_CZ_D_Archive_Sale
Asana task GID: 1213928748054248
HTML file:      campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import (
    _configure_link_templates,
    _asana_request,
    configure_target_audience,
    get_campaign_url_from_page,
    get_brand_entry,
    load_brand_config,
    save_as_draft,
    update_asana_with_braze_link,
    FIELD_TASK_STATUS,
)
from build_designed_campaign import (
    STATUS_READY_FOR_QA,
    configure_conversions_designed,
    configure_delivery_designed,
    find_campaign_api_id_by_name,
)
from create_campaign import (
    fill_html_content,
    fill_sending_settings,
    navigate_to_campaigns,
    select_html_editor,
    start_campaign_creation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BRAND         = "CZ"
TASK_GID      = "1213928748054248"
CAMPAIGN_NAME = "P_EM_2026_05_30_CZ_D_Archive_Sale"
SUBJECT       = "Rare finds from the archive"
PREHEADER     = "Up to 70% off styles that won't be restocked."
HTML_FILE     = PROJECT_ROOT / "campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html"
SEND_DATE     = "2026-05-30"

# Send time: 2026-05-30 is 5 business days from today (2026-05-23) → IT qualifies
SEND_TIME_CONFIG = {
    "type": "intelligent_timing",
    "time": None,
    "fallback_time": "16:00",
    "local_time": True,
}

# CZ Full File audience config (from data/brand_config.yaml)
CZ_FULL_FILE_AUDIENCE = {
    "type": "segment",
    "segment": '"Full File" List - September 2024',
}


# ---------------------------------------------------------------------------
# Archive old DnD campaign
# ---------------------------------------------------------------------------

def archive_old_campaign() -> None:
    """Find and archive the old incorrectly-built DnD campaign by name."""
    api_key = os.environ.get("BRAZE_API_KEY_CZ")
    base_url = (
        os.environ.get("BRAZE_BASE_URL_CZ")
        or os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
    ).rstrip("/")

    if not api_key:
        logger.warning("No BRAZE_API_KEY_CZ — skipping archive of old campaign")
        return

    logger.info(f"Looking up old campaign '{CAMPAIGN_NAME}' to archive...")
    api_id = find_campaign_api_id_by_name(CAMPAIGN_NAME, BRAND)
    if not api_id:
        logger.info(f"Old campaign '{CAMPAIGN_NAME}' not found (may already be archived or deleted) — continuing")
        return

    logger.info(f"Archiving old campaign (API ID: {api_id})...")
    try:
        resp = requests.post(
            f"{base_url}/campaigns/archive",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"campaign_ids": [api_id]},
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info("Old DnD campaign archived successfully")
        else:
            logger.warning(f"Archive returned {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.warning(f"Could not archive old campaign: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    html_body = HTML_FILE.read_text(encoding="utf-8")
    logger.info(f"HTML loaded: {len(html_body)} chars from {HTML_FILE.name}")

    # Archive the old DnD campaign before creating the new one
    archive_old_campaign()

    global_config = load_brand_config()
    brand_entry = get_brand_entry(BRAND, global_config)
    utm_templates = brand_entry.get("utm_templates", "all") if brand_entry else "all"

    braze_url: str = ""

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

        await ensure_logged_in(page)
        await select_workspace(page, BRAND)

        # ----------------------------------------------------------------
        # 1. Navigate to campaigns list
        # ----------------------------------------------------------------
        await navigate_to_campaigns(page)
        logger.info(f"On campaigns page: {page.url}")

        # ----------------------------------------------------------------
        # 2. Create campaign → Email
        # ----------------------------------------------------------------
        await start_campaign_creation(page)

        # ----------------------------------------------------------------
        # 3. Set campaign name (field is on the overview, before the modal)
        # ----------------------------------------------------------------
        name_field = page.get_by_role("textbox", name="Enter Campaign Name")
        await name_field.wait_for(state="visible", timeout=10000)
        await name_field.fill(CAMPAIGN_NAME)
        logger.info(f"Campaign name set: {CAMPAIGN_NAME}")
        await page.wait_for_timeout(500)

        # ----------------------------------------------------------------
        # 4. Select HTML code editor → opens the email editor modal
        # ----------------------------------------------------------------
        await select_html_editor(page)
        await page.wait_for_timeout(1000)

        # Debug: screenshot right after editor opens
        try:
            dbg = str(Path(__file__).parent / "debug_cz_archive_editor_open.png")
            await page.screenshot(path=dbg, full_page=False)
            logger.info(f"Editor open screenshot: {dbg}")
        except Exception:
            pass

        # ----------------------------------------------------------------
        # 5. Fill subject + preheader (Sending Settings tab in modal)
        # ----------------------------------------------------------------
        await fill_sending_settings(page, SUBJECT, PREHEADER)

        # ----------------------------------------------------------------
        # 6. Inject HTML (Content tab in modal)
        # ----------------------------------------------------------------
        await fill_html_content(page, html_body)

        # Debug: screenshot after HTML injection
        try:
            dbg2 = str(Path(__file__).parent / "debug_cz_archive_html_injected.png")
            await page.screenshot(path=dbg2, full_page=False)
            logger.info(f"HTML injected screenshot: {dbg2}")
        except Exception:
            pass

        # ----------------------------------------------------------------
        # 7. Apply UTM link templates (Link Management tab in modal)
        # ----------------------------------------------------------------
        await _configure_link_templates(page, utm_templates)

        # ----------------------------------------------------------------
        # 8. Close editor modal via Done
        # ----------------------------------------------------------------
        for done_sel in [
            page.get_by_role("button", name="Done", exact=True),
            page.locator("button:has-text('Done')").last,
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                    await done_sel.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Editor modal closed via Done")
                    break
            except Exception:
                continue

        # Debug: screenshot on compose step after closing modal
        try:
            dbg3 = str(Path(__file__).parent / "debug_cz_archive_compose.png")
            await page.screenshot(path=dbg3, full_page=False)
            logger.info(f"Compose screenshot: {dbg3}")
        except Exception:
            pass

        # ----------------------------------------------------------------
        # 9. Configure Target Audience: CZ Full File, Variant 1 = 100%
        #    configure_target_audience handles: navigate → remove control
        #    group → select segment → set variant to 100%
        # ----------------------------------------------------------------
        await configure_target_audience(page, CZ_FULL_FILE_AUDIENCE)

        # ----------------------------------------------------------------
        # 10. Configure Delivery: IT, 2026-05-30, 4:00 PM fallback
        # ----------------------------------------------------------------
        await configure_delivery_designed(page, SEND_TIME_CONFIG, SEND_DATE)

        # ----------------------------------------------------------------
        # 11. Configure Conversion Events (CZ standard: A–D, 3-day window)
        # ----------------------------------------------------------------
        await configure_conversions_designed(page, BRAND)

        # ----------------------------------------------------------------
        # 12. Save as draft
        # ----------------------------------------------------------------
        await save_as_draft(page, dry_run=False)
        await page.wait_for_timeout(2000)

        braze_url = get_campaign_url_from_page(page.url) or page.url
        logger.info(f"Campaign saved. URL: {braze_url}")

        # Final debug screenshot
        try:
            final = str(Path(__file__).parent / "debug_cz_archive_sale_final.png")
            await page.screenshot(path=final, full_page=False)
            logger.info(f"Final screenshot: {final}")
        except Exception:
            pass

        await context.close()
        await browser.close()

    if not braze_url:
        logger.error("No Braze URL captured — Asana update skipped")
        return

    # ----------------------------------------------------------------
    # 13. Update Asana
    # ----------------------------------------------------------------
    logger.info("Updating Asana task...")

    # (a) Write Braze campaign link to task
    update_asana_with_braze_link(TASK_GID, braze_url)

    # (b) Set task status → Ready for QA
    qa_payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
    if _asana_request("PUT", f"tasks/{TASK_GID}", json_data=qa_payload):
        logger.info("Task status set to Ready for QA")
    else:
        logger.warning("Could not update task status to Ready for QA")

    # (c) Post comment — tag momina_ayaz (CZ post_build_assignee) + terse template
    import html as _html
    MOMINA_GID = "1209324586499326"
    body_text = (
        "this email campaign has been automatically created in Braze "
        "and is ready for review and scheduling.\n\n"
        f"Campaign link: {braze_url}"
    )
    _url_text = _html.escape(braze_url, quote=False)
    _url_attr = _html.escape(braze_url, quote=True)
    html_body = _html.escape(body_text, quote=False)
    html_body = html_body.replace(
        _url_text,
        f'<a href="{_url_attr}">{_url_text}</a>',
    )
    html_body = f'<a data-asana-gid="{MOMINA_GID}"/>, {html_body}'
    comment_payload = {
        "data": {
            "html_text": f"<body>{html_body}</body>",
            "is_pinned": False,
        }
    }
    if _asana_request("POST", f"tasks/{TASK_GID}/stories", json_data=comment_payload):
        logger.info("Asana comment posted")
    else:
        logger.warning("Could not post Asana comment")

    print(f"\nDone! Braze URL: {braze_url}")


if __name__ == "__main__":
    asyncio.run(main())

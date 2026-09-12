#!/usr/bin/env python3
"""
One-off test: rebuild a real, already-Launched BUR designed email as a
TEST_DELETE_ campaign to confirm the _apply_utm_template() fix in
build_cz_designed_email.py selects ALL Burrow link templates (not just one).

Source task: "Sonnet Dining Chair Highlight" (Asana GID 1217034154386272,
already Launched, real Drive assets). This script re-runs the same build
pipeline as build_cz_designed_email() but:
  - Prefixes the generated campaign/template name with "TEST_DELETE_" so the
    result is unambiguous and safe to delete afterward.
  - Never calls write_back_to_asana() — the real Asana task is left untouched
    (no Braze Campaign Link field update, no status change, no comment).

After this runs, manually verify + delete the TEST_DELETE_ campaign in Braze.
"""

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test_bur_link_templates")

TASK_GID = "1217034154386272"
DRIVE_URL = "https://drive.google.com/drive/folders/1DYwpQ5uCoiGC7CvoRNDprYdJbwATW7CL?usp=drive_link"
BRAND = "BUR"


async def main() -> None:
    from build_cz_designed_email import (
        fetch_task_by_gid,
        _get_text_value,
        _get_cf_enum_name,
        _parse_slice_links,
        _parse_slice_alts,
        _parse_kickers,
        _parse_slice_layouts,
        _parse_footer_variant,
        download_images_from_drive_with_retry,
        discover_image_configs,
        upload_images,
        build_email_html,
        create_braze_template,
        build_campaign_playwright,
        load_brand_config,
        FIELD_SUBJECT_LINE,
        FIELD_PRE_HEADER,
        FIELD_SEND_TIME,
        FIELD_SEGMENT,
    )
    from utils.campaign_name import generate_campaign_name

    logger.info(f"Fetching Asana task {TASK_GID}...")
    task = fetch_task_by_gid(TASK_GID)
    if not task:
        raise RuntimeError(f"Could not fetch Asana task {TASK_GID}")

    task_name = (task.get("name") or "").strip()
    due_on = task.get("due_on") or ""
    subject = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or "7:15 AM"
    segment_name = _get_cf_enum_name(task, FIELD_SEGMENT) or "Engaged File"
    html_notes = task.get("html_notes") or ""

    real_name = generate_campaign_name(
        campaign_type="P",
        channel="EM",
        send_date=due_on,
        brand=BRAND,
        description=task_name,
        design_type="D",
    )
    campaign_name = f"TEST_DELETE_{real_name}"
    logger.info(f"Test campaign name: {campaign_name}")
    logger.info(f"Subject: {subject}")
    logger.info(f"Preheader: {preheader}")

    links = _parse_slice_links(html_notes, brand=BRAND)
    alts = _parse_slice_alts(html_notes, brand=BRAND)
    kickers = _parse_kickers(html_notes)
    layouts = _parse_slice_layouts(html_notes)

    with tempfile.TemporaryDirectory(prefix="bur_link_tpl_test_") as tmpdir:
        tmp_path = Path(tmpdir)
        logger.info("Downloading images from Google Drive...")
        local_images = await download_images_from_drive_with_retry(DRIVE_URL, tmp_path)
        if not local_images:
            raise RuntimeError("No images found in Drive folder")
        logger.info(f"Found {len(local_images)} images: {sorted(local_images.keys())}")

        image_specs = discover_image_configs(local_images, links, alts=alts, layouts=layouts, brand=BRAND)
        has_category_blocks = any(
            "category blocks" in str(p.parent).lower() for p in local_images.values()
        )
        footer_override = _parse_footer_variant(html_notes)
        if footer_override is not None:
            has_category_blocks = footer_override

        cdn_urls, oversize_errors = upload_images(local_images, brand=BRAND)
        html = build_email_html(
            cdn_urls, image_specs, has_category_blocks=has_category_blocks,
            kickers=kickers, send_date=due_on, brand=BRAND,
        )
        logger.info(f"HTML assembled: {len(html):,} chars")

        brand_config = load_brand_config()

        template_id = create_braze_template(
            html, subject=subject, preheader=preheader,
            template_name=campaign_name, dry_run=False, brand=BRAND,
        )
        logger.info(f"Template created: {template_id}")

        campaign_url = await build_campaign_playwright(
            html=html,
            subject=subject,
            preheader=preheader,
            campaign_name=campaign_name,
            send_date=due_on,
            send_time_raw=send_time_raw,
            segment_name=segment_name,
            brand_config=brand_config,
            task_name=task_name,
            dry_run=False,
            headless=True,
            brand=BRAND,
        )

    logger.info(f"DONE. Campaign URL: {campaign_url}")
    logger.info("NOTE: no Asana writeback was performed — the real task was not touched.")
    print(f"\nCAMPAIGN_URL={campaign_url}\n")


if __name__ == "__main__":
    asyncio.run(main())

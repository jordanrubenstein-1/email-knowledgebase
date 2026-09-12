#!/usr/bin/env python3
"""
Build a designed Klaviyo email campaign from Drive slice images.

Supports all Klaviyo brands (TI, TE, any future brand with a `designed_email`
section in data/brand_config.yaml).  All HTML assembly and brief-parsing logic
lives in designed_email_core.py; this script only handles the Klaviyo API calls
and Asana writeback.

API-only workflow (no Playwright):
  1. Read Asana task: SL, PH, Segment, Drive folder, HeroImage link, html_notes
  2. Parse html_notes Body Copy for per-slice layout (50/50 vs full-width) + links
  3. Download Drive images; upload to Klaviyo CDN (local cache avoids re-uploads)
  4. Build footer HTML from brand_config.yaml `designed_email.footer` config
  5. Assemble cross-client HTML (designed_email_core.assemble_html)
  6. Create Klaviyo Draft campaign → create code template → assign template
  7. Set subject / from fields
  8. Optionally write edit URL + overview URL to Asana and post comment

Adding a new Klaviyo brand:
  1. Add a `designed_email` section to data/brand_config.yaml
  2. Run: uv run python scripts/braze_automation/build_klaviyo_designed_email.py \\
          --task-gid GID --brand NEW_BRAND
  No Python changes needed.

Usage:
    # Dry run — inspect task + Drive folder, print slice plan, no API calls
    uv run python scripts/braze_automation/build_klaviyo_designed_email.py \\
      --task-gid 1214210639317072 --brand TI --dry-run

    # Build without Asana writeback (recommended during testing)
    uv run python scripts/braze_automation/build_klaviyo_designed_email.py \\
      --task-gid 1214210639317072 --brand TI --skip-asana

    # Production run (Asana writeback + status update)
    uv run python scripts/braze_automation/build_klaviyo_designed_email.py \\
      --task-gid 1214210639317072 --brand TI
"""

from __future__ import annotations

import argparse
import asyncio
import html as _html
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from designed_email_core import (
    assemble_html,
    build_footer_html,
    check_on_sale,
    classify_slice_layout,
    download_and_upload_slices,
    list_drive_slices,
    load_image_cache,
    parse_brief_slices,
    DEFAULT_IMAGE_CACHE_PATH,
    _HALF_WIDTH_FILENAME_RE,
)
from build_pt_campaign import (
    _asana_request,
    _get_text_value,
    _get_enum_value_name,
    fetch_task_by_gid,
    update_asana_with_braze_link,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    FIELD_SEGMENT,
    FIELD_SEGMENT_TEXT,
    FIELD_TASK_STATUS,
)
from build_designed_campaign import (
    STATUS_READY_FOR_QA,
    _derive_campaign_name,
    FIELD_EMAIL_SLICES,
)
from build_klaviyo_designed_campaign import (
    _load_brand_config,
    _get_audience_names,
    _resolve_audience_ids,
    AUDIENCE_TRADE_GID,
    KLAVIYO_CAMPAIGN_WIZARD_BASE,
)
from utils.klaviyo_client import KlaviyoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIELD_HERO_CTA_LINK   = "1209982221146582"  # HeroImage/Other CTA Link(s)
FIELD_AUDIENCE        = "1207522425689896"  # Audience (enum)
KLAVIYO_OVERVIEW_BASE = "https://www.klaviyo.com/campaign"

BRAND_CONFIG_PATH = PROJECT_ROOT / "data" / "brand_config.yaml"


# ---------------------------------------------------------------------------
# Brand config helpers
# ---------------------------------------------------------------------------

def _get_designed_email_cfg(brand: str) -> dict:
    """Return the `designed_email` sub-dict from brand_config.yaml, or {}."""
    with open(BRAND_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    brand_cfg = cfg.get("brands", {}).get(brand) or cfg.get(brand, {})
    return brand_cfg.get("designed_email", {})


def _get_default_link(brand: str, de_cfg: dict) -> str:
    """Return the brand homepage from designed_email config, with sensible fallbacks."""
    return de_cfg.get("homepage") or f"https://www.{brand.lower()}.com/"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def build_klaviyo_designed_email(
    task_gid: str,
    brand: str,
    dry_run: bool = False,
    skip_asana: bool = False,
    auto_confirm: bool = False,
    half_width_from: Optional[int] = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "task_gid": task_gid,
        "brand": brand,
        "dry_run": dry_run,
        "errors": [],
        "edit_url": None,
        "overview_url": None,
        "campaign_name": None,
        "slice_count": 0,
    }

    # ------------------------------------------------------------------
    # 1. Load brand config
    # ------------------------------------------------------------------
    de_cfg = _get_designed_email_cfg(brand)
    if not de_cfg:
        result["errors"].append(
            f"No `designed_email` section found in brand_config.yaml for brand {brand!r}. "
            "Add one before building."
        )
        return result

    default_link = _get_default_link(brand, de_cfg)
    footer_cfg   = de_cfg.get("footer", {})

    # ------------------------------------------------------------------
    # 2. Fetch Asana task
    # ------------------------------------------------------------------
    logger.info(f"Fetching Asana task {task_gid}...")
    task = fetch_task_by_gid(task_gid)
    if not task:
        result["errors"].append("Could not fetch Asana task")
        return result

    task_name    = task.get("name", "")
    send_date    = task.get("due_on") or ""
    subject_line = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader    = _get_text_value(task, FIELD_PRE_HEADER) or ""
    # TI reads Segment (Text) first (4-value field), falling back to the old
    # enum Segment field for older/in-flight tasks — see CLAUDE.md.
    segment_name = (
        (_get_text_value(task, FIELD_SEGMENT_TEXT) or "").strip()
        if brand == "TI"
        else ""
    ) or _get_enum_value_name(task, FIELD_SEGMENT) or ""
    folder_url   = _get_text_value(task, FIELD_EMAIL_SLICES) or ""
    hero_link    = _get_text_value(task, FIELD_HERO_CTA_LINK) or ""
    html_notes   = task.get("html_notes") or ""

    if hero_link:
        default_link = hero_link  # task-level LP overrides brand homepage

    # TE trade detection
    audience_gid = None
    for cf in (task.get("custom_fields") or []):
        if cf.get("gid") == FIELD_AUDIENCE and cf.get("enum_value"):
            audience_gid = cf["enum_value"].get("gid")
    is_trade = brand == "TE" and (
        audience_gid == AUDIENCE_TRADE_GID or "trade" in task_name.lower()
    )

    if not send_date:
        result["errors"].append("Task has no due date — set a due date before building")
        return result
    if not folder_url:
        result["errors"].append("Email Slices/Banners/Blocks Details field is empty")
        return result

    campaign_name = _derive_campaign_name("", task_name, send_date, brand)
    result["campaign_name"] = campaign_name

    # ------------------------------------------------------------------
    # 3. Parse brief + list Drive slices
    # ------------------------------------------------------------------
    brief_slices = parse_brief_slices(html_notes)
    logger.info(f"Brief slice entries parsed: {len(brief_slices)}")

    logger.info(f"Listing Drive folder: {folder_url}")
    try:
        slice_files = list_drive_slices(folder_url)
    except RuntimeError as e:
        result["errors"].append(f"Drive folder listing failed: {e}")
        return result

    if not slice_files:
        result["errors"].append("No 'Slice N' images found in Drive folder")
        return result

    result["slice_count"] = len(slice_files)

    # Pre-classify each slice
    for sf in slice_files:
        layout_result = classify_slice_layout(sf["slice_num"], sf["name"], brief_slices, half_width_from)
        sf["_layout_preclass"] = layout_result
        sf["_layout_source"] = (
            "cli"   if half_width_from is not None else
            "brief" if brief_slices.get(sf["slice_num"], {}).get("is_half_width") is not None else
            "file"  if _HALF_WIDTH_FILENAME_RE.search(sf["name"]) else
            "dims"
        )
        sf["_link_override"] = (brief_slices.get(sf["slice_num"]) or {}).get("link")
        sf["_alt_override"] = (brief_slices.get(sf["slice_num"]) or {}).get("alt")

    # Sale check and copyright year (used in summary + footer)
    send_year = int(send_date[:4]) if send_date else 2026
    on_sale   = check_on_sale(brand, send_date) if send_date else False

    # ------------------------------------------------------------------
    # Dry-run summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"DESIGNED EMAIL BUILD SUMMARY — {brand}")
    print("=" * 60)
    print(f"  Task:          {task_name}")
    print(f"  Send date:     {send_date}")
    print(f"  Campaign name: {campaign_name}")
    print(f"  Subject:       {subject_line or '(not set)'}")
    print(f"  Preheader:     {preheader or '(not set)'}")
    print(f"  Segment:       {segment_name or '(default full file)'}")
    print(f"  Default link:  {default_link}")
    print(f"  On sale:       {'yes — disclaimer included' if on_sale else 'no'}")
    print(f"  Copyright:     © {send_year} {footer_cfg.get('company_name', brand)}")
    print(f"  Drive folder:  {folder_url}")
    print(f"  Slices found:  {len(slice_files)}")
    for sf in slice_files:
        pre = sf["_layout_preclass"]
        src = sf["_layout_source"]
        layout_str = (
            f"full  ({src})" if pre is True else
            f"50/50 ({src})" if pre is False else
            "?     (dims fallback)"
        )
        print(f"    Slice {sf['slice_num']:2d}  [{layout_str}]  {sf['name']}")
        print(f"           Link: {sf['_link_override'] or default_link}")
    print("=" * 60)

    if dry_run:
        print("\nDRY RUN — no Klaviyo or Asana changes.")
        result["success"] = True
        return result

    if not auto_confirm:
        confirm = input("\nProceed? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return result

    # ------------------------------------------------------------------
    # 4. Init Klaviyo client
    # ------------------------------------------------------------------
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand.upper()}", "")
    if not api_key:
        result["errors"].append(f"KLAVIYO_API_KEY_{brand.upper()} not set in .env")
        return result
    client = KlaviyoClient(api_key, brand)

    # ------------------------------------------------------------------
    # 5. Download + upload slices (with local cache)
    # ------------------------------------------------------------------
    img_cache = load_image_cache(brand, DEFAULT_IMAGE_CACHE_PATH)
    assembled_slices = download_and_upload_slices(
        slice_files=slice_files,
        uploader=client.upload_image_from_file,
        brand=brand,
        default_link=default_link,
        img_cache=img_cache,
        cache_path=DEFAULT_IMAGE_CACHE_PATH,
    )
    if assembled_slices is None:
        result["errors"].append("One or more slice images failed to upload")
        return result

    # ------------------------------------------------------------------
    # 6. Build footer + assemble HTML
    # ------------------------------------------------------------------
    footer_html = build_footer_html(footer_cfg, send_year, on_sale)
    logger.info("Assembling email HTML...")
    email_html = assemble_html(assembled_slices, preheader=preheader, footer_html=footer_html)
    logger.info(f"HTML assembled: {len(email_html):,} chars")

    # ------------------------------------------------------------------
    # 7. Resolve audiences
    # ------------------------------------------------------------------
    brand_cfg = _load_brand_config(brand)
    sender    = brand_cfg.get("sender_info", {}).get("designed", {})
    included_names, excluded_names = _get_audience_names(
        brand_cfg, segment_name, brand=brand, is_trade=is_trade, send_date=send_date
    )
    logger.info(f"Audiences: include={included_names} exclude={excluded_names}")
    included_ids = _resolve_audience_ids(client, included_names)
    excluded_ids = _resolve_audience_ids(client, excluded_names)
    if not included_ids:
        result["errors"].append(
            f"No included audience resolved in Klaviyo for {included_names!r} — "
            "aborting rather than sending to an empty audience"
        )
        return result

    # ------------------------------------------------------------------
    # 8. Create Klaviyo Draft campaign
    # ------------------------------------------------------------------
    logger.info(f"Creating Klaviyo campaign: {campaign_name!r}")
    campaign_id = client.create_campaign(
        name=campaign_name,
        channel="email",
        included_ids=included_ids,
        excluded_ids=excluded_ids,
    )
    if not campaign_id:
        result["errors"].append("Failed to create Klaviyo campaign")
        return result
    logger.info(f"Campaign ID: {campaign_id}")

    # ------------------------------------------------------------------
    # 9. Get message ID
    # ------------------------------------------------------------------
    time.sleep(1)
    messages = client.get_campaign_messages(campaign_id)
    if not messages:
        result["errors"].append(f"Campaign {campaign_id} has no messages after creation")
        return result
    message_id = messages[0]["id"]
    logger.info(f"Message ID: {message_id}")

    # ------------------------------------------------------------------
    # 10. Create HTML template + assign
    # ------------------------------------------------------------------
    template_name = f"{campaign_name} HTML"
    logger.info(f"Creating email template: {template_name!r}")
    template_id = client.create_email_template(template_name, email_html)
    if not template_id:
        result["errors"].append("Failed to create Klaviyo email template")
        return result
    logger.info(f"Template ID: {template_id}")

    ok = client.assign_template_to_campaign_message(message_id, template_id)
    if not ok:
        logger.warning("Template assignment returned False — verify in Klaviyo")
        result["errors"].append("Template assignment may have failed — verify in Klaviyo")

    # ------------------------------------------------------------------
    # 11. Set subject / from fields
    # ------------------------------------------------------------------
    # preview_text intentionally omitted — for HTML/CSS code templates Klaviyo
    # reads from the email body; preheader is injected as a hidden div instead.
    content_update: dict = {
        "from_email":     sender.get("from_email", ""),
        "from_label":     sender.get("from_name", brand),
        "reply_to_email": sender.get("reply_to", ""),
    }
    if subject_line:
        content_update["subject"] = subject_line

    ok = client.update_campaign_message_content(message_id, content_update)
    if not ok:
        logger.warning("Failed to set subject/from fields — update manually in Klaviyo")
        result["errors"].append("Could not set subject/from fields — update manually")

    # ------------------------------------------------------------------
    # 12. Campaign URLs
    # ------------------------------------------------------------------
    edit_url     = f"{KLAVIYO_CAMPAIGN_WIZARD_BASE}/{campaign_id}/wizard/1"
    overview_url = f"{KLAVIYO_OVERVIEW_BASE}/{campaign_id}/overview"
    result["edit_url"]     = edit_url
    result["overview_url"] = overview_url
    logger.info(f"Edit URL:     {edit_url}")
    logger.info(f"Overview URL: {overview_url}")

    # ------------------------------------------------------------------
    # 13. Asana writeback
    # ------------------------------------------------------------------
    if not skip_asana:
        ok = update_asana_with_braze_link(task_gid, edit_url)
        if not ok:
            result["errors"].append("Asana link writeback failed (campaign was created)")

        qa_payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
        if _asana_request("PUT", f"tasks/{task_gid}", json_data=qa_payload):
            logger.info("Task status → Ready for QA")
        else:
            logger.warning("Could not update task status")

        assignee     = task.get("assignee") or {}
        assignee_gid = assignee.get("gid")
        body_text = (
            "this designed email campaign has been automatically built in Klaviyo. "
            "The HTML was assembled from your Drive assets — please QA all images, "
            "links, and alt text before scheduling.\n\n"
            f"Edit link: {edit_url}\n"
            f"Overview: {overview_url}"
        )
        if assignee_gid:
            escaped = _html.escape(body_text, quote=False)
            for url in (edit_url, overview_url):
                ue = _html.escape(url, quote=False)
                ua = _html.escape(url, quote=True)
                escaped = escaped.replace(ue, f'<a href="{ua}">{ue}</a>', 1)
            escaped = f'<a data-asana-gid="{assignee_gid}"/>, {escaped}'
            payload = {"data": {"html_text": f"<body>{escaped}</body>", "is_pinned": False}}
        else:
            payload = {"data": {"text": body_text, "is_pinned": False}}

        if _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload):
            logger.info("Asana comment posted")
        else:
            logger.warning("Could not post Asana comment")

    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a designed Klaviyo email campaign from Drive slice images."
    )
    parser.add_argument("--task-gid", required=True, help="Asana task GID")
    parser.add_argument("--brand", required=True,
                        help="Brand code (e.g. TI, TE). Must have a `designed_email` "
                             "section in data/brand_config.yaml.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse task + Drive folder only — no Klaviyo or Asana changes")
    parser.add_argument("--skip-asana", action="store_true",
                        help="Build in Klaviyo but skip all Asana writeback")
    parser.add_argument("--yes", action="store_true",
                        help="Auto-confirm without interactive prompt")
    parser.add_argument("--half-width-from", type=int, default=None, metavar="N",
                        help="Treat slices N and above as 50/50 (overrides brief + filename detection)")
    args = parser.parse_args()

    result = asyncio.run(
        build_klaviyo_designed_email(
            task_gid=args.task_gid,
            brand=args.brand.upper(),
            dry_run=args.dry_run,
            skip_asana=args.skip_asana,
            auto_confirm=args.yes,
            half_width_from=args.half_width_from,
        )
    )

    if result["success"]:
        if result.get("edit_url"):
            print(f"\n✓ Done!")
            print(f"  Edit:     {result['edit_url']}")
            print(f"  Overview: {result['overview_url']}")
            if result.get("errors"):
                print("\nWarnings:")
                for e in result["errors"]:
                    print(f"  ⚠ {e}")
        else:
            print("\n✓ Done (dry run)")
    else:
        errors = result.get("errors") or []
        print(f"\n✗ Failed: {'; '.join(errors)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

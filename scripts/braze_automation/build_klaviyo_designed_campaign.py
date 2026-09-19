#!/usr/bin/env python3
"""
Build designed Klaviyo email campaign shells from Asana tasks (TI brand).

API-only workflow (no Playwright):
  1. Read Asana task: Ref Braze Campaign + Subject + Preheader + Segment
  2. Find the ref campaign in Klaviyo by name
  3. Clone the ref campaign (preserves drag-and-drop template structure)
  4. Update the clone's name and audience
  5. Set subject, preview text, and from fields on the cloned campaign message
  6. Write the Klaviyo edit URL back to the Asana task

Usage:
    # Dry run — parse task fields, no Klaviyo changes
    uv run python scripts/braze_automation/build_klaviyo_designed_campaign.py \\
      --task-gid 1234567890 --brand TI --dry-run

    # Full run
    uv run python scripts/braze_automation/build_klaviyo_designed_campaign.py \\
      --task-gid 1234567890 --brand TI

    # Full run without Asana writeback
    uv run python scripts/braze_automation/build_klaviyo_designed_campaign.py \\
      --task-gid 1234567890 --brand TI --skip-asana
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from build_pt_campaign import (
    fetch_task_by_gid,
    _asana_request,
    _get_text_value,
    _get_enum_value_gid,
    _get_enum_value_name,
    update_asana_with_braze_link,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    FIELD_SEGMENT,
    FIELD_SEGMENT_TEXT,
    FIELD_AUDIENCE,
)
from build_designed_campaign import (
    FIELD_REF_BRAZE_CAMPAIGN,
    _derive_campaign_name,
)
from utils.klaviyo_client import KlaviyoClient
from utils.segment_text import resolve_ti_segment_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

KLAVIYO_BASE_API = "https://a.klaviyo.com/api"
KLAVIYO_CAMPAIGN_WIZARD_BASE = "https://www.klaviyo.com/campaign"

BRAND_CONFIG_PATH = PROJECT_ROOT / "data" / "brand_config.yaml"

AUDIENCE_TRADE_GID = "1207522425689962"  # Asana Audience field option: Trade


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_brand_config(brand: str) -> dict:
    with open(BRAND_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("brands", {}).get(brand) or cfg.get(brand, {})


def _get_audience_names(
    cfg: dict, segment_name: str, brand: str = "", is_trade: bool = False, send_date: str | None = None
) -> tuple[list[str], list[str]]:
    """
    Return (included_names, excluded_names) for Klaviyo audience resolution.

    For trade sends (is_trade=True): uses audiences.trade segment, no excludes.
    For TE consumer with "Full File" segment: returns all four tier segments.
    For all others: Asana Segment field ("Full File"/"Engaged") drives the key;
    TE defaults to "engaged" when blank, all other brands default to "full_file".
    Falls back to klaviyo.audiences.included when no audiences config entry found.

    `send_date` (Asana due_on) is only used for TI's swatch-segment cutover —
    see resolve_ti_segment_key().
    """
    klaviyo_cfg = cfg.get("klaviyo", {}).get("audiences", {})
    audiences_cfg = cfg.get("audiences", {})

    if is_trade:
        seg_key = "trade"
    elif brand == "TI":
        # TI: 4-value Segment (Text) field — see CLAUDE.md "TI Segment (Text)
        # field". Defaults to "engaged" (TI's baseline list), not "full_file".
        seg_key = resolve_ti_segment_key(segment_name, send_date=send_date)
    else:
        seg_lower = (segment_name or "").lower()
        if "engaged" in seg_lower:
            # Covers "Engaged" and "Engaged File" — engaged check always first
            seg_key = "engaged"
        elif "full" in seg_lower:
            # Covers "Full File" — note: "file" alone is intentionally excluded
            # so that "Engaged File" never accidentally maps here
            seg_key = "full_file"
        elif brand == "TE":
            seg_key = "engaged"   # TE default when segment field is blank
        else:
            seg_key = "full_file"  # all other brands keep existing default

    seg_info = audiences_cfg.get(seg_key, {})
    if seg_info:
        if "segments" in seg_info:      # multi-segment (e.g. TE Full File)
            included = list(seg_info["segments"])
        else:
            included = [seg_info.get("segment", "")]
    else:
        included = klaviyo_cfg.get("included", [])

    excluded = [] if is_trade else klaviyo_cfg.get("excluded", [])
    return [n for n in included if n], [n for n in excluded if n]


def _resolve_audience_ids(client: KlaviyoClient, names: list[str]) -> list[str]:
    """Resolve list/segment names to Klaviyo IDs, skipping unresolvable ones."""
    ids = []
    for name in names:
        rid = client.find_list_or_segment_by_name(name)
        if rid:
            ids.append(rid)
        else:
            logger.warning(f"Audience '{name}' not found in Klaviyo — skipping")
    return ids


# ---------------------------------------------------------------------------
# Campaign lookup
# ---------------------------------------------------------------------------

def _find_campaign_id_by_name(brand: str, ref_name: str) -> Optional[str]:
    """Return the Klaviyo campaign ID for an exact name match, checking all statuses."""
    import requests as _requests

    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand.upper()}", "")
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": "2024-10-15",
        "Accept": "application/vnd.api+json",
    }
    for status in ("Sent", "Draft", "Scheduled", "Cancelled"):
        params = {
            "filter": f"equals(messages.channel,'email'),equals(status,'{status}')",
            "fields[campaign]": "name,status",
            "sort": "-created_at",
        }
        try:
            resp = _requests.get(
                f"{KLAVIYO_BASE_API}/campaigns/", headers=headers, params=params, timeout=30
            )
            if resp.status_code != 200:
                continue
            for c in resp.json().get("data", []):
                if c["attributes"]["name"] == ref_name:
                    logger.info(f"Found ref campaign via API: id={c['id']} status={status}")
                    return c["id"]
        except Exception as e:
            logger.warning(f"API lookup failed for status {status}: {e}")
    return None


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

async def build_klaviyo_designed_campaign(
    task_gid: str,
    brand: str = "TI",
    dry_run: bool = True,
    skip_asana: bool = False,
    auto_confirm: bool = False,
) -> Dict[str, Any]:
    """
    Full pipeline: read Asana task → clone Klaviyo ref campaign HTML via API →
    create new Draft campaign → update details → write URL back to Asana.

    Returns a result dict with: success, braze_url, campaign_name, errors.
    """
    result: Dict[str, Any] = {
        "success": False,
        "task_gid": task_gid,
        "brand": brand,
        "dry_run": dry_run,
        "errors": [],
        "braze_url": None,
        "campaign_name": None,
    }

    # ------------------------------------------------------------------
    # 1. Fetch Asana task
    # ------------------------------------------------------------------
    logger.info(f"Fetching Asana task {task_gid}...")
    task = fetch_task_by_gid(task_gid)
    if not task:
        result["errors"].append("Could not fetch Asana task")
        return result

    task_name = task.get("name", "")
    send_date = task.get("due_on") or ""
    ref_campaign = _get_text_value(task, FIELD_REF_BRAZE_CAMPAIGN)
    subject_line = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""
    # TI reads Segment (Text) first (4-value field), falling back to the old
    # enum Segment field for older/in-flight tasks — see CLAUDE.md.
    segment_name = (
        (_get_text_value(task, FIELD_SEGMENT_TEXT) or "").strip()
        if brand == "TI"
        else ""
    ) or _get_enum_value_name(task, FIELD_SEGMENT) or ""
    audience_gid = _get_enum_value_gid(task, FIELD_AUDIENCE)
    is_trade = brand == "TE" and (
        audience_gid == AUDIENCE_TRADE_GID
        or "trade" in task_name.lower()
    )

    if not ref_campaign:
        result["errors"].append("Ref Braze Campaign field is empty on the Asana task")
        return result
    if not send_date:
        result["errors"].append(
            "Task has no due date — set a due date (the send date) before building"
        )
        return result

    new_campaign_name = _derive_campaign_name(ref_campaign, task_name, send_date, brand)
    result["campaign_name"] = new_campaign_name

    # ------------------------------------------------------------------
    # 2. Dry-run summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("KLAVIYO DESIGNED CAMPAIGN BUILD SUMMARY")
    print("=" * 60)
    print(f"  Task:              {task_name}")
    print(f"  Brand:             {brand}")
    print(f"  Send date:         {send_date}")
    print(f"  Ref campaign:      {ref_campaign}")
    print(f"  New campaign name: {new_campaign_name}")
    print(f"  Subject:           {subject_line or '(not set)'}")
    print(f"  Preheader:         {preheader or '(not set)'}")
    print(f"  Segment:           {segment_name or '(default)'}")
    if brand == "TE":
        print(f"  Trade send:        {'yes' if is_trade else 'no'}")
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

    # ------------------------------------------------------------------
    # 3. Init Klaviyo client
    # ------------------------------------------------------------------
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand.upper()}", "")
    if not api_key:
        result["errors"].append(f"KLAVIYO_API_KEY_{brand.upper()} not set in .env")
        return result
    client = KlaviyoClient(api_key, brand)

    # ------------------------------------------------------------------
    # 4. Find ref campaign by name
    # ------------------------------------------------------------------
    ref_campaign_id = _find_campaign_id_by_name(brand, ref_campaign)
    if not ref_campaign_id:
        result["errors"].append(f"Ref campaign not found in Klaviyo: {ref_campaign!r}")
        return result

    # ------------------------------------------------------------------
    # 5. Resolve audiences
    # ------------------------------------------------------------------
    cfg = _load_brand_config(brand)
    sender_key = "designed_trade" if is_trade else "designed"
    sender = cfg.get("sender_info", {}).get(sender_key) or cfg.get("sender_info", {}).get("designed", {})
    included_names, excluded_names = _get_audience_names(
        cfg, segment_name, brand=brand, is_trade=is_trade, send_date=send_date
    )
    logger.info(f"Resolving audiences: include={included_names} exclude={excluded_names}")
    included_ids = _resolve_audience_ids(client, included_names)
    excluded_ids = _resolve_audience_ids(client, excluded_names)
    if not included_ids:
        result["errors"].append(
            f"No included audience resolved in Klaviyo for {included_names!r} — "
            "aborting rather than sending to an empty audience"
        )
        return result

    # ------------------------------------------------------------------
    # 6. Clone the ref campaign (preserves drag-and-drop template)
    # ------------------------------------------------------------------
    logger.info(f"Cloning ref campaign {ref_campaign_id}...")
    new_campaign_id = client.clone_campaign(ref_campaign_id)
    if not new_campaign_id:
        result["errors"].append(f"Failed to clone ref campaign {ref_campaign_id!r}")
        return result
    logger.info(f"Cloned campaign ID: {new_campaign_id}")

    # ------------------------------------------------------------------
    # 7. Update clone's name and audience
    # ------------------------------------------------------------------
    logger.info(f"Updating campaign name to {new_campaign_name!r} and setting audience...")
    ok = client.update_campaign(
        new_campaign_id,
        name=new_campaign_name,
        included_ids=included_ids,
        excluded_ids=excluded_ids,
    )
    if not ok:
        logger.warning("Failed to update campaign name/audience — may need manual update in Klaviyo")
        result["errors"].append(
            "Could not update campaign name/audience — please update manually in Klaviyo"
        )

    # ------------------------------------------------------------------
    # 8. Get cloned campaign's message ID
    # ------------------------------------------------------------------
    time.sleep(1)
    new_messages = client.get_campaign_messages(new_campaign_id)
    if not new_messages:
        result["errors"].append(
            f"Cloned campaign {new_campaign_id} has no messages — "
            "campaign was created but content fields cannot be updated"
        )
        return result
    new_message_id = new_messages[0]["id"]
    logger.info(f"Message ID: {new_message_id}")

    # ------------------------------------------------------------------
    # 9. Set subject / preheader / from fields
    # ------------------------------------------------------------------
    content_update: dict = {
        "from_email": sender.get("from_email", "hi@theinside.com"),
        "from_label": sender.get("from_name", "The Inside"),
        "reply_to_email": sender.get("reply_to", "hi@theinside.com"),
    }
    if subject_line:
        content_update["subject"] = subject_line
    if preheader:
        content_update["preview_text"] = preheader

    ok = client.update_campaign_message_content(new_message_id, content_update)
    if not ok:
        logger.warning("Failed to set campaign message content — manual update may be needed")
        result["errors"].append(
            "Could not set subject/preheader/from fields — please update manually in Klaviyo"
        )

    # ------------------------------------------------------------------
    # 10. Construct campaign edit URL
    # ------------------------------------------------------------------
    edit_url = f"{KLAVIYO_CAMPAIGN_WIZARD_BASE}/{new_campaign_id}/wizard/1"
    result["braze_url"] = edit_url
    logger.info(f"Campaign URL: {edit_url}")

    # ------------------------------------------------------------------
    # 11. Write campaign URL back to Asana
    # ------------------------------------------------------------------
    if not skip_asana:
        ok = update_asana_with_braze_link(task_gid, edit_url)
        if ok:
            logger.info("Asana task updated with Klaviyo campaign URL")
        else:
            result["errors"].append("Asana writeback failed (campaign was created successfully)")

    # ------------------------------------------------------------------
    # 12. Post Asana comment tagging the assignee
    # ------------------------------------------------------------------
    if not skip_asana:
        import html as _html

        assignee = task.get("assignee") or {}
        assignee_gid = assignee.get("gid")

        body_text = (
            "this designed email campaign has been automatically built in Klaviyo. "
            f"The campaign was cloned from {ref_campaign!r} — the campaign name, "
            "subject line, and preview text have been updated. Please review the campaign "
            "in Klaviyo, set the send schedule, and QA all content before sending.\n\n"
            f"Campaign link: {edit_url}"
        )

        if assignee_gid:
            html_body = _html.escape(body_text, quote=False)
            url_escaped_text = _html.escape(edit_url, quote=False)
            url_escaped_attr = _html.escape(edit_url, quote=True)
            html_body = html_body.replace(
                url_escaped_text,
                f'<a href="{url_escaped_attr}">{url_escaped_text}</a>',
            )
            html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
            payload = {"data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}}
        else:
            body_text = body_text[0].upper() + body_text[1:]
            payload = {"data": {"text": body_text, "is_pinned": False}}

        comment_ok = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
        if comment_ok:
            logger.info("Posted auto-build comment on Asana task")
        else:
            logger.warning("Failed to post auto-build comment on Asana task")

    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a designed Klaviyo email campaign shell from an Asana task (API-only)."
    )
    parser.add_argument("--task-gid", required=True, help="Asana task GID")
    parser.add_argument("--brand", default="TI", choices=["TI", "TE"], help="Brand (default: TI)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no Klaviyo changes")
    parser.add_argument("--skip-asana", action="store_true", help="Skip Asana writeback")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm without prompt")
    args = parser.parse_args()

    result = asyncio.run(
        build_klaviyo_designed_campaign(
            task_gid=args.task_gid,
            brand=args.brand,
            dry_run=args.dry_run,
            skip_asana=args.skip_asana,
            auto_confirm=args.yes,
        )
    )

    if result["success"]:
        print(f"\n✓ Done: {result.get('braze_url', '(dry run)')}")
    else:
        errors = result.get("errors") or []
        print(f"\n✗ Failed: {'; '.join(errors)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

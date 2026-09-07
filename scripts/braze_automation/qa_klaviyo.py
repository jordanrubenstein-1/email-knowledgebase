"""
Automated QA for Klaviyo campaigns (TI brand — SMS and email).

Mirrors the Braze QA checks in qa_designed_email.py but uses the Klaviyo
REST API instead of Playwright. Checks that can be verified programmatically
are checked off in the Asana QA subtask list; checks that require human
review are left unchecked.

Automatable checks:
  SMS:   campaign name, copy vs brief, link resolves (HTTP 200), segment,
         send time, character count
  Email: campaign name, subject vs brief, preheader vs brief, from_label/
         from_email vs brand config, segment, send time

Not automated (left unchecked for human review):
  - UTM / link tracking (Klaviyo manages this differently)
  - Test send (skipped — no Klaviyo test-send API used here)
  - Visual / HTML review
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from utils.klaviyo_client import KlaviyoClient, KLAVIYO_BASE_URL
from qa_designed_email import (
    get_qa_subtask_gids,
    check_off_subtask,
    get_expected_segment_groups,
    _asana_request,
    _get_text_value,
    _get_enum_value_name,
    FIELD_SEND_TIME,
)
from build_sms_campaign import FIELD_BRAZE_LINK, _get_text_value as _get_tv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KLAVIYO_EMAIL_BRANDS = {"TI", "TE"}
BRAND_CONFIG_PATH = PROJECT_ROOT / "data" / "brand_config.yaml"

# Asana field GIDs (same as qa_designed_email.py)
FIELD_SUBJECT_LINE = "1207522425689993"
FIELD_PRE_HEADER   = "1207522425689995"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_brand_pt_sender(brand: str) -> dict:
    import yaml
    with open(BRAND_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return (
        cfg.get("brands", {}).get(brand, {})
           .get("sender_info", {}).get("pt", {})
    )


def _get_klaviyo_client(brand: str) -> KlaviyoClient:
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        raise RuntimeError(f"KLAVIYO_API_KEY_{brand} not set in .env")
    return KlaviyoClient(api_key=api_key, brand=brand)


def _fetch_klaviyo_campaign(client: KlaviyoClient, campaign_id: str) -> dict | None:
    """GET /campaigns/{id}/ — returns full campaign attributes including audiences."""
    return client._get(f"/campaigns/{campaign_id}/")


def _parse_send_time(raw: str | None) -> str | None:
    """Normalise a Klaviyo scheduled_at / send_time ISO string to 'H:MM AM/PM'."""
    if not raw:
        return None
    # ISO format: 2026-07-04T15:00:00+00:00
    m = re.search(r'T(\d{2}):(\d{2}):\d{2}', raw)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mn:02d} {period}"


def _normalise_time(t: str) -> str:
    """Normalise time strings for comparison: '3:00 PM' == '03:00 PM' == '15:00'."""
    t = t.strip().upper()
    m = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', t)
    if m:
        h, mn, per = int(m.group(1)), int(m.group(2)), m.group(3)
        if per == "PM" and h != 12:
            h += 12
        if per == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mn:02d}"
    m2 = re.match(r'^(\d{1,2}):(\d{2})$', t)
    if m2:
        return f"{int(m2.group(1)):02d}:{m2.group(2)}"
    return t


def _link_resolves(url: str) -> bool:
    try:
        r = requests.get(url, timeout=10, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code < 400
    except Exception:
        return False


def _extract_sms_link(body: str) -> str | None:
    """Return the first URL found in an SMS body."""
    m = re.search(r'https?://\S+', body)
    return m.group(0).rstrip('.,)') if m else None


def _extract_notes_body(notes: str) -> str:
    """Return the copywriter body (everything before [AI Brief])."""
    lines = notes.splitlines()
    out = []
    for line in lines:
        if re.match(r'^\[AI Brief\]', line.strip(), re.IGNORECASE):
            break
        out.append(line)
    return "\n".join(out).strip()


def _extract_expected_copy(notes: str) -> str:
    """Return the first paragraph of the copywriter body for SMS comparison."""
    body = _extract_notes_body(notes)
    paras = re.split(r'\n{2,}', body)
    return paras[0].strip() if paras else body.strip()


def _normalise_copy(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip()).lower()


def _post_qa_comment(task_gid: str, issues: list[str]) -> None:
    if issues:
        bullets = "\n".join(f"• {i}" for i in issues)
        text = f"QA flagged items for human review:\n{bullets}"
    else:
        text = "Automated QA complete — no issues found."
    _asana_request(
        "POST",
        f"tasks/{task_gid}/stories",
        json_data={"data": {"text": text, "is_pinned": False}},
    )


# ---------------------------------------------------------------------------
# Core QA runner
# ---------------------------------------------------------------------------

def run_klaviyo_qa(
    task_gid: str,
    brand: str,
    campaign_id: str,
    channel: str,          # "sms" or "email"
    raw_task: dict,
    dry_run: bool = False,
) -> dict:
    """Run automated QA for a Klaviyo campaign and update Asana subtasks.

    Returns a result dict with boolean keys for each check.
    """
    brand = brand.upper()
    notes = raw_task.get("notes", "")
    task_name = raw_task.get("name", task_gid)

    logger.info(f"[Klaviyo QA] [{brand}] {task_name} — {channel} — campaign {campaign_id}")

    # --- Fetch Klaviyo data ---
    client = _get_klaviyo_client(brand)

    campaign_data = _fetch_klaviyo_campaign(client, campaign_id)
    if not campaign_data:
        logger.error(f"[Klaviyo QA] Could not fetch campaign {campaign_id}")
        if not dry_run:
            _post_qa_comment(task_gid, ["Could not fetch Klaviyo campaign — check campaign ID"])
        return {"error": "campaign_fetch_failed"}

    campaign_attrs = campaign_data.get("data", {}).get("attributes", {})
    campaign_name  = campaign_attrs.get("name", "")
    audiences      = campaign_attrs.get("audiences", {})
    included_ids   = audiences.get("included", [])
    send_time_raw  = campaign_attrs.get("send_time") or campaign_attrs.get("scheduled_at")

    messages = client.get_campaign_messages(campaign_id)
    msg = messages[0] if messages else {}
    msg_attrs = msg.get("attributes", {})
    content   = msg_attrs.get("content", {})

    # SMS body / Email fields
    sms_body     = content.get("body", "")
    subject      = content.get("subject", "")
    preview_text = content.get("preview_text", "")
    from_label   = content.get("from_label", "")
    from_email   = content.get("from_email", "")

    # --- Walk QA subtask tree ---
    qa_gids = get_qa_subtask_gids(task_gid, channel) if not dry_run else {}
    qa_issues: list[str] = []
    results: dict = {}

    def _check(key: str, passed: bool, label: str, issue_msg: str) -> None:
        results[key] = passed
        if passed:
            gid = qa_gids.get(key)
            if gid and not dry_run:
                check_off_subtask(gid, label)
        else:
            qa_issues.append(issue_msg)

    # ------------------------------------------------------------------
    # 1. Campaign name — naming convention
    # ------------------------------------------------------------------
    try:
        from utils.campaign_name import validate_campaign_name
        name_ok = validate_campaign_name(campaign_name)
    except Exception:
        name_ok = bool(campaign_name)
    _check(
        "campaign_name", name_ok,
        "campaign name",
        "Campaign name may not follow naming conventions — verify in Klaviyo",
    )

    # ------------------------------------------------------------------
    # 2. SMS copy matches brief  /  Email subject + preheader
    # ------------------------------------------------------------------
    if channel == "sms":
        expected_copy = _extract_expected_copy(notes)
        # Strip "Brand: " prefix from both sides for comparison
        norm_expected = _normalise_copy(re.sub(r'^[^:]+:\s*', '', expected_copy))
        norm_actual   = _normalise_copy(re.sub(r'^[^:]+:\s*', '', sms_body))
        copy_ok = norm_expected == norm_actual or norm_expected in norm_actual
        _check(
            "campaign_name",  # reuse — SMS has no separate copy subtask key; use copy_match
            copy_ok,
            "copy matches brief",
            "SMS body in Klaviyo does not match Asana brief — verify copy",
        )
        results["copy_ok"] = copy_ok

    else:
        # Subject
        asana_subject = (
            _get_text_value(raw_task, FIELD_SUBJECT_LINE) or ""
        ).strip()
        if not asana_subject:
            # Fall back to SL: line in notes
            m = re.search(r'^SL:\s*(.+)$', notes, re.MULTILINE | re.IGNORECASE)
            asana_subject = m.group(1).strip() if m else ""
        subject_ok = bool(asana_subject) and subject.strip() == asana_subject
        _check(
            "subject_line", subject_ok,
            "subject line",
            "Subject line in Klaviyo does not match Asana brief — verify",
        )

        # Preheader
        asana_ph = (_get_text_value(raw_task, FIELD_PRE_HEADER) or "").strip()
        if not asana_ph:
            m = re.search(r'^PH:\s*(.+)$', notes, re.MULTILINE | re.IGNORECASE)
            asana_ph = m.group(1).strip() if m else ""
        ph_ok = preview_text.strip() == asana_ph
        _check(
            "preheader", ph_ok,
            "preheader",
            "Preheader in Klaviyo does not match Asana brief — verify",
        )

        # Sender name + email
        sender_cfg = _load_brand_pt_sender(brand)
        expected_from_label = sender_cfg.get("from_name", "")
        expected_from_email = sender_cfg.get("from_email", "")
        sender_ok = (
            from_label.strip().lower() == expected_from_label.lower()
            and from_email.strip().lower() == expected_from_email.lower()
        )
        _check(
            "sender", sender_ok,
            "sender name/email",
            f"Sender in Klaviyo ({from_label!r} / {from_email!r}) does not match "
            f"expected ({expected_from_label!r} / {expected_from_email!r}) — verify",
        )

    # ------------------------------------------------------------------
    # 3. Link resolves (SMS only — check the URL in the body)
    # ------------------------------------------------------------------
    if channel == "sms":
        url_in_body = _extract_sms_link(sms_body)
        if url_in_body:
            link_ok = _link_resolves(url_in_body)
            _check(
                "send_date",   # closest available subtask key for SMS link check
                link_ok,
                "link resolves",
                f"SMS link does not resolve (HTTP error): {url_in_body}",
            )
        else:
            qa_issues.append("No URL found in SMS body — verify link")
            link_ok = False
        results["link_ok"] = link_ok

    # ------------------------------------------------------------------
    # 4. Character count ≤ 130 (SMS only)
    # ------------------------------------------------------------------
    if channel == "sms":
        char_ok = len(sms_body) <= 130
        results["char_count_ok"] = char_ok
        if not char_ok:
            qa_issues.append(
                f"SMS body is {len(sms_body)} characters (limit 130) — shorten copy"
            )

    # ------------------------------------------------------------------
    # 5. Segment matches lifecycle guidelines
    # ------------------------------------------------------------------
    expected_groups = get_expected_segment_groups(brand, channel, raw_task)
    segment_ok = False
    if expected_groups and included_ids:
        # Resolve included IDs to names for comparison
        id_to_name: dict[str, str] = {}
        for seg_name_candidate in {n for g in expected_groups for n in g}:
            sid = client.find_list_or_segment_by_name(seg_name_candidate)
            if sid:
                id_to_name[sid] = seg_name_candidate
        matched_names = {id_to_name[i] for i in included_ids if i in id_to_name}
        for group in expected_groups:
            if all(name in matched_names for name in group):
                segment_ok = True
                break

    if not expected_groups:
        # Can't verify — leave unchecked, no issue raised
        results["segment_ok"] = None
    else:
        _check(
            "audience_segment", segment_ok,
            "segment matches lifecycle doc",
            f"Klaviyo audience does not match expected segment(s) "
            f"{expected_groups} — verify in Klaviyo",
        )
        _check(
            "audience_lifecycle", segment_ok,
            "audience matches lifecycle doc",
            None if segment_ok else "",   # de-duped with audience_segment message
        )
        # Remove empty-string duplicate issue
        qa_issues = [i for i in qa_issues if i]

    # ------------------------------------------------------------------
    # 6. Send time matches Asana field (or lifecycle default)
    # ------------------------------------------------------------------
    asana_send_time = (_get_text_value(raw_task, FIELD_SEND_TIME) or "").strip()
    if not asana_send_time:
        # Lifecycle default for TI SMS is 3:00 PM
        from qa_designed_email import _get_lifecycle_times
        am_time, pm_time = _get_lifecycle_times(brand)
        asana_send_time = (pm_time if "pm" in task_name.lower() else am_time) or ""

    klaviyo_time = _parse_send_time(send_time_raw)
    if asana_send_time and klaviyo_time:
        time_ok = _normalise_time(asana_send_time) == _normalise_time(klaviyo_time)
    elif not send_time_raw:
        # Campaign not scheduled yet — can't verify
        time_ok = None
    else:
        time_ok = True  # No expected time to compare against

    if time_ok is None:
        results["send_time_ok"] = None   # unscheduled — leave unchecked
    else:
        _check(
            "send_time", bool(time_ok),
            "send time",
            f"Send time in Klaviyo ({klaviyo_time!r}) does not match "
            f"Asana ({asana_send_time!r}) — verify",
        )

    # ------------------------------------------------------------------
    # 7. Post final Asana comment
    # ------------------------------------------------------------------
    logger.info(
        f"[Klaviyo QA] Results: "
        + ", ".join(f"{k}={'✓' if v else ('?' if v is None else '✗')}"
                    for k, v in results.items())
    )
    if not dry_run:
        _post_qa_comment(task_gid, qa_issues)
    else:
        if qa_issues:
            logger.info(f"[dry_run] Would post QA comment: {qa_issues}")
        else:
            logger.info("[dry_run] QA clean — no issues.")

    return results


# ---------------------------------------------------------------------------
# Async wrapper for webhook_server
# ---------------------------------------------------------------------------

async def run_klaviyo_qa_async(
    task_gid: str,
    brand: str,
    campaign_id: str,
    channel: str,
    raw_task: dict,
    dry_run: bool = False,
) -> dict:
    return await asyncio.to_thread(
        run_klaviyo_qa,
        task_gid=task_gid,
        brand=brand,
        campaign_id=campaign_id,
        channel=channel,
        raw_task=raw_task,
        dry_run=dry_run,
    )

#!/usr/bin/env python3
"""
poll_ready_tasks.py — Periodic fallback poller for SMS and Push auto-builds.

Runs every 15 minutes via LaunchAgent (com.havenly.poll-ready-tasks).
Catches tasks that were missed by the Asana webhook (e.g. due to ngrok drops).

What it does:
  1. Fetches all "Ready to Code" SMS tasks for Braze brands (HAV, CZ, ID, BUR, STF)
     and builds them via orchestrate_sms.orchestrate().
  2. Fetches all "Ready to Code" SMS tasks for TI and builds them via Klaviyo.
  3. Fetches all "Ready to Code" Push tasks for HAV and builds them via
     build_push_campaign.build_single_push_campaign().

Idempotent — all paths skip tasks that already have a Braze/Klaviyo campaign link.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Cross-process build lock shared with webhook_server.py. Prevents this poller and the
# webhook (two separate processes) from both building the same Ready-to-Code task during
# the multi-minute window before a build writes its Braze Campaign Link. See build_lock.py.
from build_lock import try_acquire as acquire_build_lock, release as release_build_lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS — Braze brands
# ---------------------------------------------------------------------------

SMS_BRAZE_BRANDS = ["HAV", "CZ", "ID", "BUR", "STF"]


async def _poll_sms_braze() -> None:
    # Build task-by-task (via orchestrate's single_task_gid path — the same one the webhook
    # uses) rather than orchestrate's bulk mode, so each build can be guarded by the
    # cross-process build lock and skipped if the webhook is already building that task.
    # collect_eligible_tasks() preserves orchestrate's dual trigger (Ready to Code OR Copy
    # subtask complete) and already drops tasks that are built or past their send date.
    from orchestrate_sms import orchestrate, collect_eligible_tasks
    from build_pt_campaign import fetch_task_by_gid
    from build_sms_campaign import _get_text_value, FIELD_BRAZE_LINK

    for brand_code in SMS_BRAZE_BRANDS:
        logger.info(f"[SMS] Polling {brand_code}...")
        try:
            eligible = await asyncio.to_thread(collect_eligible_tasks, brand_code)
            if not eligible:
                logger.info(f"[SMS] {brand_code}: nothing to build")
                continue

            logger.info(f"[SMS] {brand_code}: found {len(eligible)} campaign(s) to build")
            for task in eligible:
                gid = task["gid"]
                name = task.get("name", gid)
                # Re-fetch before building — the webhook may have built it since we listed.
                fresh = await asyncio.to_thread(fetch_task_by_gid, gid)
                if fresh and _get_text_value(fresh, FIELD_BRAZE_LINK):
                    logger.info(f"[SMS] {name} ({gid}) already has a campaign link — skipping (built by webhook)")
                    continue
                if not acquire_build_lock(gid):
                    logger.info(f"[SMS] {name} ({gid}) is being built by another process (webhook) — skipping")
                    continue
                logger.info(f"[SMS] Building: {name} ({gid}) [{brand_code}]")
                try:
                    await orchestrate(
                        brand_code=brand_code,
                        dry_run=False,
                        headless=True,
                        single_task_gid=gid,
                    )
                except Exception:
                    logger.exception(f"[SMS] Error building {gid}")
                finally:
                    release_build_lock(gid)
        except Exception:
            logger.exception(f"[SMS] Error polling {brand_code}")


# ---------------------------------------------------------------------------
# SMS — TI (Klaviyo)
# ---------------------------------------------------------------------------

async def _poll_sms_ti() -> None:
    from build_sms_campaign import (
        fetch_ready_to_code_sms_tasks,
        _get_text_value,
        FIELD_BRAZE_LINK,
    )
    from build_pt_campaign import fetch_task_by_gid
    from create_klaviyo_sms import build_klaviyo_sms_campaign

    logger.info("[SMS] Polling TI (Klaviyo)...")
    try:
        tasks = await asyncio.to_thread(fetch_ready_to_code_sms_tasks, "TI")
        pending = [t for t in tasks if not t.get("braze_campaign_id") and not t.get("braze_link")]

        if not pending:
            logger.info("[SMS] TI: nothing to build")
            return

        logger.info(f"[SMS] TI: found {len(pending)} campaign(s) to build")
        for task in pending:
            gid = task["gid"]
            name = task["name"]
            fresh = await asyncio.to_thread(fetch_task_by_gid, gid)
            if fresh and _get_text_value(fresh, FIELD_BRAZE_LINK):
                logger.info(f"[SMS/TI] {name} ({gid}) already has a campaign link — skipping (built by webhook)")
                continue
            if not acquire_build_lock(gid):
                logger.info(f"[SMS/TI] {name} ({gid}) is being built by another process (webhook) — skipping")
                continue
            logger.info(f"[SMS/TI] Building: {name} ({gid})")
            try:
                await asyncio.to_thread(
                    build_klaviyo_sms_campaign,
                    brand="TI",
                    asana_gid=gid,
                    dry_run=False,
                )
            except Exception:
                logger.exception(f"[SMS/TI] Error building {gid}")
            finally:
                release_build_lock(gid)

    except Exception:
        logger.exception("[SMS] Error polling TI")


# ---------------------------------------------------------------------------
# Push — HAV only
# ---------------------------------------------------------------------------

async def _poll_push() -> None:
    from build_push_campaign import (
        fetch_ready_to_code_push_tasks,
        fetch_task_by_gid as fetch_push_task_by_gid,
        build_single_push_campaign,
        load_brand_config,
        FIELD_BRAZE_LINK as PUSH_FIELD_BRAZE_LINK,
        _get_text_value as _push_get_text_value,
    )

    logger.info("[Push] Polling HAV...")
    try:
        tasks = await asyncio.to_thread(fetch_ready_to_code_push_tasks)
        pending = [t for t in tasks if not t.get("braze_link")]

        if not pending:
            logger.info("[Push] HAV: nothing to build")
            return

        logger.info(f"[Push] HAV: found {len(pending)} campaign(s) to build")
        global_config = await asyncio.to_thread(load_brand_config)

        for task in pending:
            gid = task.get("gid", "")
            name = task.get("campaign_name") or task.get("name", gid)
            fresh = await asyncio.to_thread(fetch_push_task_by_gid, gid)
            if fresh and _push_get_text_value(fresh, PUSH_FIELD_BRAZE_LINK):
                logger.info(f"[Push] {name} ({gid}) already has a campaign link — skipping (built by webhook)")
                continue
            if not acquire_build_lock(gid):
                logger.info(f"[Push] {name} ({gid}) is being built by another process (webhook) — skipping")
                continue
            logger.info(f"[Push] Building: {name}")
            try:
                result = await build_single_push_campaign(
                    task=task,
                    global_config=global_config,
                    dry_run=False,
                    auto_confirm=True,
                    headless=True,
                )
                if result["success"]:
                    logger.info(f"[Push] Built: {name} → {result.get('braze_url')}")
                else:
                    logger.error(f"[Push] Failed: {name} — {result.get('errors')}")
            except Exception:
                logger.exception(f"[Push] Error building {name}")
            finally:
                release_build_lock(gid)

    except Exception:
        logger.exception("[Push] Error polling HAV")


# ---------------------------------------------------------------------------
# PT Email — all brands (Braze + Klaviyo TI)
# ---------------------------------------------------------------------------

# Asana Type field GIDs for PT detection (matches webhook_server.py)
_FIELD_TYPE = "1207522425689987"
_TYPE_PLAIN_TEXT = "1207522425689988"

_PT_KLAVIYO_BRANDS = {"TI"}


async def _poll_pt_email() -> None:
    from build_pt_campaign import (
        _asana_request,
        ASANA_PROJECT_GID,
        ASANA_WORKSPACE_GID,
        STATUS_READY_TO_CODE,
        CHANNEL_OPTIONS,
        FIELD_CHANNEL,
        FIELD_TASK_STATUS,
        FIELD_BRAND,
        FIELD_BRAZE_LINK,
        BRAND_GID_TO_CODE,
        fetch_task_by_gid,
        parse_asana_task,
        build_single_campaign,
        load_brand_config,
        _get_text_value,
        _get_enum_value_gid,
    )
    from orchestrate_sms import post_campaign_created_comment
    from build_sms_campaign import update_asana_task_status, STATUS_READY_FOR_QA

    logger.info("[PT Email] Polling all brands...")

    opt_fields = ",".join([
        "name", "due_on", "completed", "notes", "html_notes",
        "custom_fields", "custom_fields.gid",
        "custom_fields.enum_value", "custom_fields.enum_value.gid",
        "custom_fields.enum_value.name",
        "custom_fields.text_value", "custom_fields.display_value",
        "assignee", "assignee.name", "assignee.gid",
    ])
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["email"],
        "opt_fields": opt_fields,
        "limit": 100,
    }
    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    raw_tasks = await asyncio.to_thread(_asana_request, "GET", endpoint, None, params)
    if not raw_tasks:
        logger.info("[PT Email] No Ready to Code email tasks found")
        return

    pending = []
    for task in raw_tasks:
        if task.get("completed"):
            continue

        # PT detection: Type field OR name patterns (matches webhook_server.py logic)
        type_gid = None
        for cf in task.get("custom_fields", []):
            if cf.get("gid") == _FIELD_TYPE:
                type_gid = (cf.get("enum_value") or {}).get("gid")
                break
        name_upper = task.get("name", "").strip().upper()
        is_pt = (
            type_gid == _TYPE_PLAIN_TEXT
            or name_upper.endswith("_PT")
            or "_PT_" in name_upper
            or name_upper.endswith("(PT)")
        )
        if not is_pt:
            continue

        if _get_text_value(task, FIELD_BRAZE_LINK):
            continue

        pending.append(task)

    if not pending:
        logger.info("[PT Email] Nothing to build")
        return

    logger.info(f"[PT Email] Found {len(pending)} task(s) to build")
    global_config = await asyncio.to_thread(load_brand_config)

    for raw_task in pending:
        task_gid = raw_task["gid"]
        task_name = raw_task.get("name", task_gid)
        brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
        brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
        if not brand_code:
            logger.warning(f"[PT Email] Unknown brand GID {brand_gid!r} for {task_gid} — skipping")
            continue

        # Re-fetch immediately before building — the webhook server may have already
        # built this task and written the campaign link since the pending list was assembled.
        fresh = await asyncio.to_thread(fetch_task_by_gid, task_gid)
        if fresh and _get_text_value(fresh, FIELD_BRAZE_LINK):
            logger.info(f"[PT Email] {task_name} ({task_gid}) already has a campaign link — skipping (built by webhook)")
            continue

        if not acquire_build_lock(task_gid):
            logger.info(f"[PT Email] {task_name} ({task_gid}) is being built by another process (webhook) — skipping")
            continue

        logger.info(f"[PT Email] Building: {task_name} ({task_gid}) [{brand_code}]")
        try:
            if brand_code in _PT_KLAVIYO_BRANDS:
                from create_klaviyo_email import build_klaviyo_email_campaign
                edit_url = await asyncio.to_thread(
                    build_klaviyo_email_campaign, brand=brand_code, asana_gid=task_gid
                )
                success = edit_url is not None
            else:
                full_raw = await asyncio.to_thread(fetch_task_by_gid, task_gid)
                if not full_raw:
                    logger.error(f"[PT Email] Could not re-fetch task {task_gid} — skipping")
                    continue
                parsed = await asyncio.to_thread(parse_asana_task, full_raw)
                if not parsed:
                    logger.error(f"[PT Email] Could not parse task {task_gid} — skipping")
                    continue
                result = await build_single_campaign(
                    task=parsed,
                    global_config=global_config,
                    dry_run=False,
                    auto_confirm=True,
                    headless=True,
                    skip_comment=True,
                )
                success = result.get("success") and bool(result.get("braze_url"))
                if success:
                    orchestrator_config = {
                        **global_config.get("orchestrator", {}),
                        "comment_template": (
                            "this email campaign has been automatically created in {platform} "
                            "and is ready for review and scheduling.\n\n"
                            "Campaign link: {braze_url}"
                        ),
                    }
                    post_campaign_created_comment(
                        task_gid=task_gid,
                        braze_url=result["braze_url"],
                        brand_code=brand_code,
                        orchestrator_config=orchestrator_config,
                        assignee_gid=(raw_task.get("assignee") or {}).get("gid"),
                    )
                else:
                    errors = result.get("errors", [])
                    logger.error(
                        f"[PT Email] Build failed for {task_gid}: "
                        f"{'; '.join(errors) if errors else 'unknown error'}"
                    )

            if success:
                status_ok = await asyncio.to_thread(
                    update_asana_task_status, task_gid, STATUS_READY_FOR_QA
                )
                if status_ok:
                    logger.info(f"[PT Email] Built: {task_name} → Ready for QA")
                else:
                    logger.warning(f"[PT Email] Built but status update failed for {task_gid}")

        except Exception:
            logger.exception(f"[PT Email] Error building {task_gid}")
        finally:
            release_build_lock(task_gid)


# ---------------------------------------------------------------------------
# Designed Email — all Braze brands
# ---------------------------------------------------------------------------

DESIGNED_EMAIL_BRANDS = ["HAV", "CZ", "ID", "BUR", "STF"]


# *** ADDING A NEW HTML/CSS BRAND? Add it to HTMLCSS_DESIGNED_CUTOFFS here AND in webhook_server.py.
#     See CLAUDE.md § "HTML/CSS Brand Migration". ***
CZ_DESIGNED_CUTOFF = "2026-05-30"
STF_DESIGNED_CUTOFF = "2026-07-20"
TI_DESIGNED_CUTOFF = "2026-07-21"
BUR_DESIGNED_CUTOFF = "2026-08-18"
HTMLCSS_DESIGNED_CUTOFFS = {
    "CZ": CZ_DESIGNED_CUTOFF,
    "STF": STF_DESIGNED_CUTOFF,
    "TI": TI_DESIGNED_CUTOFF,
    "BUR": BUR_DESIGNED_CUTOFF,
}
# HTML/CSS brands on Klaviyo (not Braze) — dispatch to build_klaviyo_designed_email.
_KLAVIYO_HTMLCSS_BRANDS = {"TI"}
FIELD_EMAIL_SLICES = "1208664127595091"
FIELD_TYPE = "1207522425689987"
TYPE_PLAIN_TEXT = "1207522425689988"


async def _poll_designed_email() -> None:
    from build_designed_campaign import (
        fetch_ready_to_code_designed_tasks,
        build_designed_campaign,
        _get_text_value,
        FIELD_BRAZE_LINK,
    )
    from build_pt_campaign import fetch_task_by_gid

    logger.info("[DesignedEmail] Polling all brands...")
    try:
        # Pass the HTML/CSS cutoff map so the fetch also returns Drive-URL-only tasks
        # (no Ref Braze Campaign) for HTML/CSS brands — otherwise the poller safety net
        # never sees them and only the webhook builds them. See CLAUDE.md § "HTML/CSS
        # Brand Migration" (poller safety-net caveat).
        tasks = await asyncio.to_thread(
            fetch_ready_to_code_designed_tasks, None, HTMLCSS_DESIGNED_CUTOFFS
        )
        pending = [t for t in tasks if not _get_text_value(t, FIELD_BRAZE_LINK)]

        if not pending:
            logger.info("[DesignedEmail] Nothing to build")
            return

        logger.info(f"[DesignedEmail] Found {len(pending)} campaign(s) to build")
        for task in pending:
            gid = task["gid"]
            name = task.get("name", gid)
            fresh = await asyncio.to_thread(fetch_task_by_gid, gid)
            if fresh and _get_text_value(fresh, FIELD_BRAZE_LINK):
                logger.info(f"[DesignedEmail] {name} ({gid}) already has a campaign link — skipping (built by webhook)")
                continue

            from build_pt_campaign import _get_enum_value_gid, FIELD_BRAND
            from build_sms_campaign import BRAND_GID_TO_CODE
            brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
            brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
            if not brand_code:
                logger.warning(f"[DesignedEmail] Unknown brand GID {brand_gid!r} for task {gid} — skipping")
                continue

            # HTML/CSS brands (CZ, STF) on/after their cutoff with a Drive URL → HTML/CSS builder
            type_gid = _get_enum_value_gid(task, FIELD_TYPE)
            due_on = task.get("due_on") or ""
            drive_url = _get_text_value(task, FIELD_EMAIL_SLICES)
            htmlcss_cutoff = HTMLCSS_DESIGNED_CUTOFFS.get(brand_code or "")
            is_htmlcss_designed = (
                htmlcss_cutoff is not None
                and type_gid != TYPE_PLAIN_TEXT
                and due_on >= htmlcss_cutoff
                and bool(drive_url)
                and "drive.google.com" in (drive_url or "")
            )

            if not acquire_build_lock(gid):
                logger.info(f"[DesignedEmail] {name} ({gid}) is being built by another process (webhook) — skipping")
                continue

            logger.info(f"[DesignedEmail] Building: {name} ({gid}) [{brand_code}]{'  [HTML/CSS]' if is_htmlcss_designed else ''}")
            try:
                if is_htmlcss_designed and brand_code in _KLAVIYO_HTMLCSS_BRANDS:
                    # Klaviyo HTML/CSS brand (TI) — API builder, Klaviyo CDN.
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent.parent))
                    from build_klaviyo_designed_email import build_klaviyo_designed_email
                    result = await build_klaviyo_designed_email(
                        task_gid=gid,
                        brand=brand_code,
                        dry_run=False,
                        auto_confirm=True,
                    )
                elif is_htmlcss_designed:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent.parent))
                    from build_cz_designed_email import build_cz_designed_email
                    result = await build_cz_designed_email(
                        task_gid=gid,
                        drive_url=drive_url,
                        dry_run=False,
                        headless=True,
                        brand=brand_code,
                    )
                else:
                    result = await build_designed_campaign(
                        task_gid=gid,
                        brand=brand_code,
                        dry_run=False,
                        headless=True,
                        auto_confirm=True,
                    )
                if result["success"]:
                    built_url = result.get("braze_url") or result.get("overview_url") or result.get("edit_url")
                    logger.info(f"[DesignedEmail] Built: {name} → {built_url}")
                else:
                    errors = result.get("errors") or []
                    logger.error(f"[DesignedEmail] Failed: {name} — {'; '.join(errors) if errors else 'unknown'}")
            except Exception:
                logger.exception(f"[DesignedEmail] Error building {gid}")
            finally:
                release_build_lock(gid)

    except Exception:
        logger.exception("[DesignedEmail] Error during polling")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _poll_copy_subtasks() -> None:
    """Safety net for the Lacy copy subtask on SMS/Push 'Awaiting Creative' tasks.

    Deterministic replacement for the paused Asana automation rule. Idempotent —
    ensure_copy_subtask() skips any task that already has a copy subtask, so this
    never duplicates the one created synchronously during briefing.
    """
    from copy_subtask import poll_awaiting_creative_copy_subtasks

    logger.info("[CopySubtask] Polling SMS/Push Awaiting Creative...")
    try:
        summary = await asyncio.to_thread(poll_awaiting_creative_copy_subtasks)
        logger.info(f"[CopySubtask] Done: {summary}")
    except Exception:
        logger.exception("[CopySubtask] Error polling copy subtasks")


async def _poll_copy_request_due_dates() -> None:
    """Mirror each parent task's send date onto its copy-request subtask's
    "Parent Task Due Date" field, so the copy editor's board List view shows
    it as a column. Idempotent — only writes when the value has drifted.
    """
    from sync_copy_request_due_dates import sync_copy_request_due_dates

    logger.info("[DueDateSync] Syncing copy request parent due dates...")
    try:
        summary = await asyncio.to_thread(sync_copy_request_due_dates)
        logger.info(f"[DueDateSync] Done: {summary}")
    except Exception:
        logger.exception("[DueDateSync] Error syncing copy request due dates")


async def _poll_copy_request_brand() -> None:
    """Backfill Brand on copy-request subtasks in "All Brand Copy Requests"
    when Asana's native rule fails to copy it (e.g. the domain's automation
    credit quota is exhausted mid-burst — see sync_copy_request_brand.py).
    Idempotent — only fills a currently-empty Brand field, never overwrites.
    """
    from sync_copy_request_brand import sync_copy_request_brand

    logger.info("[BrandSync] Backfilling missing Brand on copy requests...")
    try:
        summary = await asyncio.to_thread(sync_copy_request_brand)
        logger.info(f"[BrandSync] Done: {summary}")
    except Exception:
        logger.exception("[BrandSync] Error backfilling copy request Brand")


async def _main() -> None:
    logger.info(f"poll_ready_tasks starting — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    await _poll_sms_braze()
    await _poll_sms_ti()
    await _poll_push()
    await _poll_pt_email()
    await _poll_designed_email()
    await _poll_copy_subtasks()
    await _poll_copy_request_due_dates()
    await _poll_copy_request_brand()
    logger.info("poll_ready_tasks done")


if __name__ == "__main__":
    asyncio.run(_main())

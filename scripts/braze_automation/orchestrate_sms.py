#!/usr/bin/env python3
"""
SMS Campaign Orchestrator — status-driven automation for Braze campaign creation.

Polls Asana for SMS tasks that are ready for automated campaign creation,
dispatches the existing SMS builder, and posts a comment on the Asana task
tagging the relevant brand owners with the Braze campaign link.

A task is eligible if EITHER of these conditions is met (whichever first):
  1. Task status custom field = "Ready to Code"
  2. Any subtask whose name contains "Copy" is marked complete

De-duplication: tasks that already have a Braze link are skipped.

Usage:
    # Preview — show what would be processed (default)
    uv run python scripts/braze_automation/orchestrate_sms.py --brand STF --dry-run

    # Actually build campaigns in Braze
    uv run python scripts/braze_automation/orchestrate_sms.py \\
        --brand STF --no-dry-run --headless

    # Process a single task by GID
    uv run python scripts/braze_automation/orchestrate_sms.py \\
        --task 1234567890 --no-dry-run --headless
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import html as _html
import yaml
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

# Import the existing SMS builder components
from build_sms_campaign import (
    fetch_ready_to_code_sms_tasks,
    fetch_task_by_gid,
    parse_asana_task,
    build_single_campaign,
    load_brand_config,
    update_asana_with_braze_link,
    update_asana_task_status,
    _asana_request,
    _asana_headers,
    _get_text_value,
    ASANA_BASE_URL,
    ASANA_PROJECT_GID,
    ASANA_WORKSPACE_GID,
    FIELD_BRAND,
    FIELD_CHANNEL,
    FIELD_TASK_STATUS,
    FIELD_BRAZE_LINK,
    FIELD_BRAZE_CAMPAIGN_ID,
    STATUS_READY_TO_CODE,
    STATUS_READY_FOR_QA,
    BRAND_OPTIONS,
    BRAND_GID_TO_CODE,
    CHANNEL_OPTIONS,
    CHANNEL_GID_TO_NAME,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_orchestrator_config() -> Dict[str, Any]:
    """Load orchestrator config from brand_config.yaml."""
    config_path = PROJECT_ROOT / "data" / "brand_config.yaml"
    with open(config_path) as f:
        full_config = yaml.safe_load(f)
    return full_config.get("orchestrator", {})


# =========================================================================
# ASANA SUBTASK QUERIES
# =========================================================================

def fetch_sms_tasks_for_brand(brand_code: str) -> List[Dict]:
    """Fetch all non-completed SMS tasks for a brand (regardless of status).

    Used by the "Copy subtask complete" trigger path. Returns all SMS tasks
    that are not completed and don't already have a Braze link, so we can
    check their subtasks.
    """
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["sms"],
        f"custom_fields.{FIELD_BRAND}.value": BRAND_OPTIONS.get(brand_code.upper(), ""),
        "completed": False,
        "opt_fields": ",".join([
            "name", "due_on", "completed", "notes",
            "custom_fields", "custom_fields.gid",
            "custom_fields.enum_value", "custom_fields.enum_value.gid",
            "custom_fields.enum_value.name",
            "custom_fields.text_value", "custom_fields.display_value",
            "assignee", "assignee.name", "assignee.gid",
        ]),
        "limit": 100,
    }

    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    tasks_data = _asana_request("GET", endpoint, params=params)
    if not tasks_data:
        return []

    results = []
    for task in tasks_data:
        if task.get("completed"):
            continue
        parsed = parse_asana_task(task)
        if parsed:
            results.append(parsed)
    return results


def has_copy_subtask_complete(task_gid: str) -> bool:
    """Check if any subtask containing 'Copy' in its name is completed.

    Uses GET /tasks/{task_gid}/subtasks to list subtasks, then checks
    for any with 'Copy' (case-insensitive) in the name that is completed.
    """
    endpoint = f"tasks/{task_gid}/subtasks"
    params = {"opt_fields": "name,completed", "limit": 100}
    subtasks = _asana_request("GET", endpoint, params=params)

    if not subtasks:
        return False

    for subtask in subtasks:
        name = subtask.get("name", "")
        if re.search(r"copy", name, re.IGNORECASE) and subtask.get("completed"):
            logger.info(
                f"  Subtask '{name}' (gid={subtask['gid']}) is complete — "
                f"task qualifies via Copy-complete trigger"
            )
            return True

    return False


def fetch_copy_complete_sms_tasks(brand_code: str) -> List[Dict]:
    """Fetch SMS tasks where a 'Copy' subtask is complete (regardless of parent status).

    This is the second trigger path: even if the parent task status is NOT
    'Ready to Code', if the Copy subtask is checked off, the task qualifies.

    Tasks that already have a Braze link are excluded.
    """
    all_sms_tasks = fetch_sms_tasks_for_brand(brand_code)
    logger.info(f"Checking {len(all_sms_tasks)} SMS tasks for completed Copy subtasks...")

    eligible = []
    for task in all_sms_tasks:
        # Skip if already built (braze_campaign_id or braze_link — automation writes the latter)
        if task.get("braze_campaign_id") or task.get("braze_link"):
            continue

        if has_copy_subtask_complete(task["gid"]):
            eligible.append(task)

    return eligible


# =========================================================================
# MERGE & DEDUP
# =========================================================================

def collect_eligible_tasks(
    brand_code: str,
    single_task_gid: Optional[str] = None,
) -> List[Dict]:
    """Collect all eligible SMS tasks using both trigger paths.

    Path A: Status = 'Ready to Code' (existing query)
    Path B: Copy subtask is completed (new query)

    Returns a deduplicated list merged by task GID.
    """
    if single_task_gid:
        # Single-task mode: fetch and check eligibility directly
        logger.info(f"Single-task mode: fetching task {single_task_gid}...")
        raw_task = fetch_task_by_gid(single_task_gid)
        if not raw_task:
            logger.error(f"Could not fetch task {single_task_gid}")
            return []
        parsed = parse_asana_task(raw_task)
        if not parsed:
            logger.error(f"Task {single_task_gid} could not be parsed (missing brand/channel?)")
            return []
        if parsed.get("braze_campaign_id") or parsed.get("braze_link"):
            logger.info(f"Task {single_task_gid} already built — skipping")
            return []
        due_on = parsed.get("due_on")
        if due_on and due_on < datetime.now().strftime("%Y-%m-%d"):
            logger.warning(
                f"Task {single_task_gid} send date {due_on} is in the past — skipping"
            )
            return []
        return [parsed]

    tasks_by_gid: Dict[str, Dict] = {}
    trigger_sources: Dict[str, List[str]] = {}

    today = datetime.now().strftime("%Y-%m-%d")

    def _is_eligible(t: Dict) -> bool:
        if t.get("braze_campaign_id") or t.get("braze_link"):
            return False
        due_on = t.get("due_on")
        if due_on and due_on < today:
            logger.warning(f"  Skipping '{t['name']}' — send date {due_on} is in the past")
            return False
        return True

    # Path A: "Ready to Code" status
    logger.info(f"[Path A] Fetching 'Ready to Code' SMS tasks for {brand_code}...")
    ready_tasks = [t for t in fetch_ready_to_code_sms_tasks(brand_filter=brand_code) if _is_eligible(t)]
    logger.info(f"  Found {len(ready_tasks)} task(s) via Ready to Code status")

    for task in ready_tasks:
        gid = task["gid"]
        tasks_by_gid[gid] = task
        trigger_sources.setdefault(gid, []).append("Ready to Code")

    # Path B: Copy subtask completed
    logger.info(f"[Path B] Checking for completed Copy subtasks for {brand_code}...")
    copy_tasks = [t for t in fetch_copy_complete_sms_tasks(brand_code) if _is_eligible(t)]
    logger.info(f"  Found {len(copy_tasks)} task(s) via Copy subtask complete")

    for task in copy_tasks:
        gid = task["gid"]
        if gid not in tasks_by_gid:
            tasks_by_gid[gid] = task
        trigger_sources.setdefault(gid, []).append("Copy subtask complete")

    # Log trigger info per task
    for gid, sources in trigger_sources.items():
        task = tasks_by_gid[gid]
        logger.info(f"  Eligible: {task['name']} (triggers: {', '.join(sources)})")

    return list(tasks_by_gid.values())


# =========================================================================
# ASANA TASK UPDATES
# =========================================================================

def reassign_asana_task(task_gid: str, assignee_gid: str) -> bool:
    """Reassign an Asana task to a new user."""
    payload = {"data": {"assignee": assignee_gid}}
    result = _asana_request("PUT", f"tasks/{task_gid}", json_data=payload)
    return result is not None


# =========================================================================
# ASANA COMMENTING
# =========================================================================

def post_campaign_created_comment(
    task_gid: str,
    braze_url: str,
    brand_code: str,
    orchestrator_config: Dict[str, Any],
    assignee_gid: Optional[str] = None,
) -> bool:
    """Post an Asana comment on the task with @-mentions and the Braze link.

    Uses the Asana Stories API (POST /tasks/{task_gid}/stories) with html_text
    to create @-mentions via <a data-asana-gid="USER_GID"/> syntax.

    Args:
        task_gid: Asana task GID to comment on.
        braze_url: URL to the created Braze campaign.
        brand_code: Brand code (e.g. "STF") to look up owners.
        orchestrator_config: The 'orchestrator' section from brand_config.yaml.
        assignee_gid: Asana GID of the task assignee to tag on the first line.

    Returns:
        True if comment was posted successfully.
    """
    comment_template = orchestrator_config.get("comment_template", "")

    # Build the comment body text
    _klaviyo_brands = {"TI"}
    platform = "Klaviyo" if brand_code in _klaviyo_brands else "Braze"
    body_text = comment_template.strip().format(braze_url=braze_url, platform=platform)

    if assignee_gid:
        # Tag the assignee at the start of the first line via html_text.
        # Escape & < > in body_text — Braze URLs contain & params that must be &amp;
        # Do NOT use <br>: Asana rejects it and stores the block as raw literal text.
        html_body = _html.escape(body_text, quote=False)
        _url_text = _html.escape(braze_url, quote=False)
        _url_attr = _html.escape(braze_url, quote=True)
        html_body = html_body.replace(
            _url_text,
            f'<a href="{_url_attr}">{_url_text}</a>',
        )
        html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
        payload = {
            "data": {
                "html_text": f"<body>{html_body}</body>",
                "is_pinned": False,
            }
        }
    else:
        body_text = body_text[0].upper() + body_text[1:]
        payload = {
            "data": {
                "text": body_text,
                "is_pinned": False,
            }
        }

    result = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
    if result:
        logger.info(f"Posted comment on task {task_gid}")
        return True
    else:
        logger.error(f"Failed to post comment on task {task_gid}")
        return False


# =========================================================================
# ORCHESTRATION LOOP
# =========================================================================

async def orchestrate(
    brand_code: str,
    dry_run: bool = True,
    headless: bool = True,
    single_task_gid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Main orchestration loop.

    1. Collect eligible tasks (dual-trigger: Ready to Code OR Copy subtask complete)
    2. For each task, dispatch build_single_campaign()
    3. On success, post Asana comment tagging brand owners

    Args:
        brand_code: Brand to process (e.g. "STF").
        dry_run: If True, preview only — no Braze builds or Asana comments.
        headless: If True, run Playwright in headless mode.
        single_task_gid: If set, process only this task.

    Returns:
        List of result dicts from build_single_campaign().
    """
    # Load configs
    global_config = load_brand_config()
    orchestrator_config = load_orchestrator_config()

    # Collect eligible tasks
    eligible_tasks = collect_eligible_tasks(brand_code, single_task_gid)

    if not eligible_tasks:
        print("\nNo eligible SMS tasks found to process.")
        return []

    print(f"\n{'=' * 60}")
    print(f"SMS ORCHESTRATOR — {brand_code}")
    print(f"{'=' * 60}")
    print(f"  Eligible tasks: {len(eligible_tasks)}")
    print(f"  Dry run:        {dry_run}")
    print(f"  Headless:       {headless}")
    print(f"{'=' * 60}")

    for i, task in enumerate(eligible_tasks, 1):
        print(f"\n  [{i}] {task['name']}")
        print(f"      GID: {task['gid']}  |  Due: {task.get('due_on', 'N/A')}")

    if dry_run:
        print(f"\n{'=' * 60}")
        print("DRY RUN — previewing builds (no Braze campaigns or comments will be created)")
        print(f"{'=' * 60}")

    results = []
    for i, task in enumerate(eligible_tasks, 1):
        print(f"\n{'—' * 60}")
        print(f"[{i}/{len(eligible_tasks)}] Processing: {task['brand']} — {task['name']}")
        print(f"{'—' * 60}")

        if brand_code == "TI":
            # TI SMS campaigns are built in Klaviyo, not Braze
            from create_klaviyo_sms import build_klaviyo_sms_campaign
            try:
                klaviyo_url = await asyncio.to_thread(
                    build_klaviyo_sms_campaign,
                    brand="TI",
                    asana_gid=task["gid"],
                    dry_run=dry_run,
                )
                result = {
                    "success": klaviyo_url is not None,
                    "braze_url": klaviyo_url,
                    "task_name": task["name"],
                    "errors": [] if klaviyo_url else ["Klaviyo campaign creation failed"],
                }
            except Exception as exc:
                logger.exception(f"Klaviyo SMS build failed for task {task['gid']}")
                result = {
                    "success": False,
                    "braze_url": None,
                    "task_name": task["name"],
                    "errors": [str(exc)],
                }
        else:
            # Braze brands — dispatch to the existing builder
            result = await build_single_campaign(
                task=task,
                global_config=global_config,
                dry_run=dry_run,
                auto_confirm=True,
                headless=headless,
            )
        results.append(result)

        # Post Asana comment on success (non-dry-run only).
        # TI SMS: build_klaviyo_sms_campaign() already posts its own comment — skip here.
        if result["success"] and result.get("braze_url") and not dry_run and brand_code != "TI":
            # Resolve post-build assignee (overrides existing task assignee for comment + reassign)
            asana_users = orchestrator_config.get("asana_users", {})
            post_build_key = orchestrator_config.get("post_build_assignee", {}).get(brand_code)
            comment_assignee_gid = (
                asana_users.get(post_build_key) if post_build_key else task.get("assignee_gid")
            )

            # Reassign task if a post-build assignee is configured
            if post_build_key and comment_assignee_gid:
                print(f"\n  Reassigning task to {post_build_key}...")
                reassign_ok = reassign_asana_task(task["gid"], comment_assignee_gid)
                if reassign_ok:
                    print(f"  Task reassigned to {post_build_key}.")
                else:
                    print(f"  WARNING: Failed to reassign task.")

            print(f"\n  Posting Asana comment with Braze link...")
            comment_ok = post_campaign_created_comment(
                task_gid=task["gid"],
                braze_url=result["braze_url"],
                brand_code=brand_code,
                orchestrator_config=orchestrator_config,
                assignee_gid=comment_assignee_gid,
            )
            if comment_ok:
                print(f"  Comment posted successfully.")
            else:
                print(f"  WARNING: Failed to post comment (campaign was still created).")

            # Surface a copy-verification warning if the SMS body could not be
            # confirmed to match the brief. The campaign was still built and
            # linked; a human reconciles the copy in Braze before dispatch.
            copy_warnings = result.get("copy_warnings", [])
            if copy_warnings:
                issues_text = "\n".join(f"  • {w}" for w in copy_warnings)
                copy_comment_ok = _asana_request(
                    "POST",
                    f"tasks/{task['gid']}/stories",
                    json_data={
                        "data": {
                            "text": (
                                f"⚠️ SMS copy could not be automatically verified — please "
                                f"confirm the SMS body in Braze matches the brief before "
                                f"dispatching:\n\n{issues_text}"
                            ),
                            "is_pinned": False,
                        }
                    },
                )
                if copy_comment_ok:
                    print(f"  Copy warning comment posted ({len(copy_warnings)} issue(s)).")
                else:
                    print(f"  WARNING: Failed to post copy warning comment.")

        # Always update status to Ready for QA on success (applies to all brands including TI).
        if result["success"] and not dry_run:
            status_ok = update_asana_task_status(task["gid"], STATUS_READY_FOR_QA)
            if status_ok:
                print(f"  Status updated to 'Ready for QA'.")
            else:
                print(f"  WARNING: Failed to update task status to Ready for QA.")
        elif result["success"] and dry_run:
            print(f"\n  [DRY RUN] Would post comment tagging: "
                  f"{', '.join(orchestrator_config.get('brand_owners', {}).get(brand_code, []))}")

    # Summary
    print(f"\n{'=' * 60}")
    print("ORCHESTRATOR SUMMARY")
    print(f"{'=' * 60}")
    success_count = sum(1 for r in results if r["success"])
    failed_count = sum(1 for r in results if not r["success"])
    print(f"  Processed: {len(results)}")
    print(f"  Success:   {success_count}")
    print(f"  Failed:    {failed_count}")
    if dry_run:
        print("  (dry run — no changes were made)")
    else:
        for r in results:
            if r["success"] and r.get("braze_url"):
                print(f"  Created: {r['task_name']} → {r['braze_url']}")
            elif not r["success"]:
                print(f"  FAILED:  {r['task_name']} — {'; '.join(r.get('errors', []))}")
    print(f"{'=' * 60}")

    return results


# =========================================================================
# CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SMS Campaign Orchestrator — polls Asana and builds SMS campaigns in Braze."
    )
    parser.add_argument(
        "--brand", type=str, default="STF",
        help="Brand to process (default: STF). E.g. HAV, CZ, ID, BUR, STF, TI",
    )
    parser.add_argument(
        "--task", type=str,
        help="Process a single Asana task by GID (bypasses polling)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview without building (default: True)",
    )
    parser.add_argument(
        "--no-dry-run", action="store_true",
        help="Actually build campaigns in Braze and post Asana comments",
    )
    parser.add_argument(
        "--no-headless", action="store_false", dest="headless",
        help="Show browser window (default: headless)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    dry_run = not args.no_dry_run
    brand_code = args.brand.upper()

    # Validate brand
    if brand_code not in BRAND_OPTIONS:
        print(f"Error: Unknown brand '{brand_code}'. Valid: {', '.join(sorted(BRAND_OPTIONS.keys()))}")
        sys.exit(1)

    print(f"\nSMS Orchestrator starting — brand={brand_code}, dry_run={dry_run}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    results = asyncio.run(
        orchestrate(
            brand_code=brand_code,
            dry_run=dry_run,
            headless=args.headless,
            single_task_gid=args.task,
        )
    )

    # Exit with non-zero code if any failures
    if any(not r["success"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()

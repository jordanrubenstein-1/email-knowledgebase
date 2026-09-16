#!/usr/bin/env python3
"""
sync_copy_request_due_dates.py — mirrors each parent task's send date onto a
"Parent Task Due Date" custom field on its copy-request subtask, so the copy
editor can see it as a column in the "All Brand Copy Requests" board's List
view. Named generically (not "Email Due Date") because copy requests also
cover SMS and other non-email channels.

Why a separate custom field instead of the subtask's own Due Date: copy
subtasks already have their own due date, tiered by copy_subtask.py (brief +
2/3/4 working days) to spread Lacy's workload. Overwriting that with the
parent's send date would break the tiering, so this syncs a dedicated field
instead of the native Due Date.

Idempotent — only writes when the field's current value differs from the
parent's due_on. Tasks with no parent (orphaned/standalone board cards), a
parent with no due_on, or a parent due_on that's already in the past are
skipped — the field is only populated for upcoming sends.

Usage:
    uv run python scripts/braze_automation/sync_copy_request_due_dates.py [--dry-run]
    uv run python scripts/braze_automation/sync_copy_request_due_dates.py --task-gid GID [--dry-run]
"""

import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional

from copy_subtask import _asana_request

logger = logging.getLogger(__name__)

COPY_REQUESTS_PROJECT_GID = "1207353785125845"  # All Brand Copy Requests
FIELD_PARENT_DUE_DATE = "1216738664684902"  # "Parent Task Due Date"

_OPT_FIELDS = "name,completed,parent.name,parent.due_on,custom_fields"


def _current_field_value(task: Dict) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == FIELD_PARENT_DUE_DATE:
            return cf.get("date_value", {}).get("date") if cf.get("date_value") else None
    return None


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _sync_one_task(task: Dict, dry_run: bool, summary: Dict) -> None:
    gid = task.get("gid")
    parent = task.get("parent")
    if not parent or not parent.get("due_on"):
        summary["skipped"] += 1
        return
    parent_due = parent["due_on"]
    if parent_due < _today_str():
        summary["skipped"] += 1
        return
    if _current_field_value(task) == parent_due:
        summary["skipped"] += 1
        return
    if dry_run:
        logger.info(f"[DueDateSync] would set {task.get('name', gid)} -> {parent_due}")
        summary["dry_run"] += 1
        return
    updated = _asana_request(
        "PUT",
        f"tasks/{gid}",
        json_data={"data": {"custom_fields": {FIELD_PARENT_DUE_DATE: {"date": parent_due}}}},
    )
    if updated is None:
        summary["error"] += 1
        return
    logger.info(f"[DueDateSync] synced {task.get('name', gid)} -> {parent_due}")
    summary["synced"] += 1


def sync_copy_request_due_date_for_task(task_gid: str, dry_run: bool = False) -> Dict:
    """Sync Parent Task Due Date for a single copy-request task (testing/manual use)."""
    summary = {"synced": 0, "skipped": 0, "error": 0, "dry_run": 0}
    task = _asana_request("GET", f"tasks/{task_gid}", params={"opt_fields": _OPT_FIELDS})
    if not task:
        summary["error"] += 1
        return summary
    if task.get("completed"):
        summary["skipped"] += 1
        return summary
    _sync_one_task(task, dry_run, summary)
    return summary


def sync_copy_request_due_dates(dry_run: bool = False) -> Dict:
    """Sync Parent Task Due Date on every incomplete task in the copy-requests board."""
    summary = {"synced": 0, "skipped": 0, "error": 0, "dry_run": 0}
    tasks: List[Dict] = _asana_request(
        "GET",
        f"projects/{COPY_REQUESTS_PROJECT_GID}/tasks",
        params={"opt_fields": _OPT_FIELDS, "limit": 100},
    ) or []

    for task in tasks:
        if task.get("completed"):
            continue
        _sync_one_task(task, dry_run, summary)

    return summary


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Sync parent task due dates onto copy-request subtasks")
    parser.add_argument("--task-gid", help="Sync a single copy-request task GID (testing/manual use)")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing to Asana")
    args = parser.parse_args()

    if args.task_gid:
        summary = sync_copy_request_due_date_for_task(args.task_gid, dry_run=args.dry_run)
    else:
        summary = sync_copy_request_due_dates(dry_run=args.dry_run)
    print(f"Copy request due-date sync complete: {summary}")


if __name__ == "__main__":
    _main()

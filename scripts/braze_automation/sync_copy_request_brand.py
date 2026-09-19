#!/usr/bin/env python3
"""
sync_copy_request_brand.py — backfills the "Brand" custom field onto
copy-request subtasks in the "All Brand Copy Requests" board from their
parent task's Brand, when Asana's native rule fails to copy it.

Why this exists: the copy-request subtask ("[Task Name] Copy") is created by
a native Asana rule (see copy_subtask.py header) whose steps include copying
the parent's Brand field onto the new subtask. That step consumes an Asana
"automation credit," and when the workspace's credit quota is exhausted
mid-burst (e.g. a large batch of calendar tasks briefed in one sitting), the
subtask still gets created/assigned/commented, but the Brand-copy step
silently no-ops — Asana surfaces this as an `automation_step_credit_rate_limited`
story on the parent, not an error anywhere visible on the subtask itself.
Raising the credit limit isn't an option here, so this script is the
deterministic backstop. Confirmed cause 2026-07-30 (14 ID copy-request
subtasks briefed in one session all missing Brand, each with a matching
credit-limit story on its parent).

Only backfills — never overwrites. If the subtask already has a Brand set
(whatever the value), it's left alone; this only fills a currently-empty
field, so a legitimate manual correction is never clobbered. Idempotent and
safe to run repeatedly — a subtask that already has a Brand value is a no-op.

Usage:
    uv run python scripts/braze_automation/sync_copy_request_brand.py [--dry-run]
    uv run python scripts/braze_automation/sync_copy_request_brand.py --task-gid GID [--dry-run]
"""

import argparse
import logging
from typing import Dict, List, Optional

from copy_subtask import _asana_request

logger = logging.getLogger(__name__)

COPY_REQUESTS_PROJECT_GID = "1207353785125845"  # All Brand Copy Requests
FIELD_BRAND = "1207522425689880"  # "Brand"

_OPT_FIELDS = ",".join([
    "name", "completed",
    "custom_fields", "custom_fields.gid", "custom_fields.enum_value",
    "custom_fields.enum_value.gid", "custom_fields.enum_value.name",
    "parent.name",
    "parent.custom_fields", "parent.custom_fields.gid",
    "parent.custom_fields.enum_value", "parent.custom_fields.enum_value.gid",
    "parent.custom_fields.enum_value.name",
])


def _brand_gid(custom_fields: List[Dict]) -> Optional[str]:
    for cf in custom_fields or []:
        if cf.get("gid") == FIELD_BRAND:
            enum_value = cf.get("enum_value")
            return enum_value.get("gid") if enum_value else None
    return None


def _sync_one_task(task: Dict, dry_run: bool, summary: Dict) -> None:
    gid = task.get("gid")
    parent = task.get("parent")
    if not parent:
        summary["skipped"] += 1
        return

    # Already has a Brand — never overwrite, even if it looks wrong; that's a
    # manual-correction case, not this script's job.
    if _brand_gid(task.get("custom_fields", [])):
        summary["skipped"] += 1
        return

    parent_brand_gid = _brand_gid(parent.get("custom_fields", []))
    if not parent_brand_gid:
        # Parent itself has no Brand set — nothing to backfill from.
        summary["skipped"] += 1
        return

    if dry_run:
        logger.info(f"[BrandSync] would set {task.get('name', gid)} -> {parent_brand_gid}")
        summary["dry_run"] += 1
        return

    updated = _asana_request(
        "PUT",
        f"tasks/{gid}",
        json_data={"data": {"custom_fields": {FIELD_BRAND: parent_brand_gid}}},
    )
    if updated is None:
        summary["error"] += 1
        return
    logger.info(f"[BrandSync] synced {task.get('name', gid)} -> {parent_brand_gid}")
    summary["synced"] += 1


def sync_copy_request_brand_for_task(task_gid: str, dry_run: bool = False) -> Dict:
    """Backfill Brand for a single copy-request task (testing/manual use)."""
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


def sync_copy_request_brand(dry_run: bool = False) -> Dict:
    """Backfill Brand on every incomplete task in the copy-requests board that
    is missing it, using each task's parent Brand as the source of truth."""
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
    parser = argparse.ArgumentParser(description="Backfill missing Brand on copy-request subtasks from their parent")
    parser.add_argument("--task-gid", help="Backfill a single copy-request task GID (testing/manual use)")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing to Asana")
    args = parser.parse_args()

    if args.task_gid:
        summary = sync_copy_request_brand_for_task(args.task_gid, dry_run=args.dry_run)
    else:
        summary = sync_copy_request_brand(dry_run=args.dry_run)
    print(f"Copy request Brand backfill complete: {summary}")


if __name__ == "__main__":
    _main()

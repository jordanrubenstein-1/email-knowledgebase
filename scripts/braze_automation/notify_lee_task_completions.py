#!/usr/bin/env python3
"""
notify_lee_task_completions.py — Slack alert when Lee Mayer directly marks a
task complete on Master CRM (Email & SMS), so the team can catch accidental
completions.

Runs every 10 minutes via LaunchAgent (com.havenly.notify-lee-completions).
Idempotent — dedups on the Asana story gid of the completion event (data/
lee_task_completion_notifications.yaml), so re-running never double-posts,
and a task that's reopened + re-completed by Lee correctly re-alerts (new
story gid).

Scope: only top-level tasks in the project (excludes the high-volume
auto-generated QA checklist subtasks that live in the same project).

Detection: this specifically targets Lee accidentally clicking the "mark
complete" checkbox herself — not a status change that happens to trigger an
Asana rule that auto-completes the task (those show created_by: null on the
marked_complete story, since Asana itself is the nominal actor). So the
match is literal: only alert when the marked_complete story's
created_by.gid is Lee's GID directly. Anything else is skipped.

Usage:
    uv run python scripts/braze_automation/notify_lee_task_completions.py [--dry-run] [--lookback-hours N]
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from build_sms_campaign import _asana_request, ASANA_PROJECT_GID, ASANA_WORKSPACE_GID
from utils.slack_client import post_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

LEE_MAYER_GID = "5257594239997"  # lee@havenly.com
STATE_FILE = PROJECT_ROOT / "data" / "lee_task_completion_notifications.yaml"
DEFAULT_LOOKBACK_HOURS = 6  # generous vs. the 10-min poll interval; dedup makes overlap safe

MESSAGE_TEMPLATE = (
    "This task was marked complete by Lee - please verify that it wasn't "
    "marked complete by accident: {link}"
)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"checked_story_gids": []}
    with open(STATE_FILE) as f:
        return yaml.safe_load(f) or {"checked_story_gids": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def fetch_recently_completed_top_level_tasks(lookback_hours: int) -> list:
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "projects.any": ASANA_PROJECT_GID,
        "completed": "true",
        "completed_at.after": since,
        "opt_fields": "gid,name,parent,permalink_url",
        "limit": 100,
    }
    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    tasks = _asana_request("GET", endpoint, params=params) or []
    # Top-level tasks only — excludes auto-generated QA checklist subtasks,
    # which are also members of this project and complete far more often.
    return [t for t in tasks if t.get("parent") is None]


def find_marked_complete_actor(task_gid: str):
    """Return (story_gid, actor_gid) for the most recent 'marked_complete'
    story on this task, or (None, None) if no such story exists."""
    stories = _asana_request(
        "GET",
        f"tasks/{task_gid}/stories",
        params={"opt_fields": "resource_subtype,created_by.gid,created_at"},
    ) or []
    marked_complete = [s for s in stories if s.get("resource_subtype") == "marked_complete"]
    if not marked_complete:
        return None, None
    story = marked_complete[-1]  # most recent
    actor_gid = (story.get("created_by") or {}).get("gid")
    return story["gid"], actor_gid


def run(dry_run: bool = False, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> dict:
    state = load_state()
    checked = set(state.get("checked_story_gids", []))
    summary = {"checked": 0, "notified": 0, "skipped_not_lee": 0, "skipped_dedup": 0, "errors": 0}

    tasks = fetch_recently_completed_top_level_tasks(lookback_hours)
    logger.info(f"Found {len(tasks)} completed top-level task(s) in lookback window")

    for task in tasks:
        gid = task["gid"]
        try:
            story_gid, actor_gid = find_marked_complete_actor(gid)
        except Exception:
            logger.exception(f"Error resolving completion actor for {gid}")
            summary["errors"] += 1
            continue
        if not story_gid:
            continue
        summary["checked"] += 1
        if story_gid in checked:
            summary["skipped_dedup"] += 1
            continue
        if actor_gid != LEE_MAYER_GID:
            checked.add(story_gid)  # cache so we don't re-check this event every 10 min
            summary["skipped_not_lee"] += 1
            continue

        link = task.get("permalink_url")
        text = MESSAGE_TEMPLATE.format(link=link)
        if dry_run:
            logger.info(f"[DRY RUN] Would post: {text}")
            summary["notified"] += 1
            checked.add(story_gid)
        else:
            if post_message(text):
                logger.info(f"Posted Slack alert for {task.get('name')} ({gid})")
                summary["notified"] += 1
                checked.add(story_gid)
            else:
                summary["errors"] += 1
                # don't mark as checked — retry next run

    state["checked_story_gids"] = sorted(checked)
    save_state(state)
    return summary


def _main():
    parser = argparse.ArgumentParser(
        description="Alert #team-lifecycle when Lee Mayer directly completes a Master CRM task"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print instead of posting to Slack")
    parser.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    args = parser.parse_args()
    summary = run(dry_run=args.dry_run, lookback_hours=args.lookback_hours)
    print(f"notify_lee_task_completions complete: {summary}")


if __name__ == "__main__":
    _main()

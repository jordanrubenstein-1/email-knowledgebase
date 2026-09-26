"""reset_braze_links.py — Clear FIELD_BRAZE_LINK from SMS and/or push Asana tasks.

Clears the Braze campaign link field so the webhook server will treat the task
as "not yet built" and re-trigger auto-build when status is Ready to Code.

Usage:
    # Dry run (show what would be cleared)
    uv run python scripts/braze_automation/reset_braze_links.py --dry-run

    # Clear all SMS tasks that have a Braze link (any status)
    uv run python scripts/braze_automation/reset_braze_links.py --channel sms

    # Clear push tasks in Ready to Code status only
    uv run python scripts/braze_automation/reset_braze_links.py --channel push --status ready

    # Clear both SMS and push (default)
    uv run python scripts/braze_automation/reset_braze_links.py

    # Clear a specific task by GID
    uv run python scripts/braze_automation/reset_braze_links.py --task-gid 1234567890
"""

import argparse
import os
import sys
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants (mirrors build_sms_campaign.py)
# ---------------------------------------------------------------------------
ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"

FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_BRAZE_LINK = "1210710306792280"

STATUS_READY_TO_CODE = "1209995669275789"

CHANNEL_OPTIONS = {
    "email": "1207562370794989",
    "sms": "1207562370794990",
    "push": "1207562370794991",
}


def _asana_headers() -> dict:
    token = os.environ.get("ASANA_API_KEY") or os.environ.get("ASANA_TOKEN")
    if not token:
        sys.exit("ASANA_API_KEY not set in .env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _asana_request(method: str, endpoint: str, json_data=None, params=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=_asana_headers(),
                            json=json_data, params=params, timeout=30)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  [rate-limited] waiting {wait}s...")
        time.sleep(wait)
        resp = requests.request(method, url, headers=_asana_headers(),
                                json=json_data, params=params, timeout=30)
    if resp.status_code not in (200, 201):
        print(f"  [error] Asana {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json().get("data")


def _get_text_value(task: dict, field_gid: str) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            return cf.get("text_value") or cf.get("display_value") or None
    return None


def search_tasks(channel_gids: list[str], status_gid: Optional[str]) -> list[dict]:
    """Search Asana for tasks matching the given channel(s) and optional status."""
    all_tasks = []
    opt_fields = "name,gid,custom_fields"

    for channel_gid in channel_gids:
        params = {
            "projects.any": ASANA_PROJECT_GID,
            f"custom_fields.{FIELD_CHANNEL}.value": channel_gid,
            "opt_fields": opt_fields,
            "limit": 100,
        }
        if status_gid:
            params[f"custom_fields.{FIELD_TASK_STATUS}.value"] = status_gid

        endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
        data = _asana_request("GET", endpoint, params=params)
        if data:
            all_tasks.extend(data)

    return all_tasks


def clear_braze_link(task_gid: str) -> bool:
    """Set FIELD_BRAZE_LINK to null on the given task."""
    payload = {"data": {"custom_fields": {FIELD_BRAZE_LINK: None}}}
    result = _asana_request("PUT", f"tasks/{task_gid}", json_data=payload)
    return result is not None


def main():
    parser = argparse.ArgumentParser(description="Clear Braze links from SMS/push Asana tasks")
    parser.add_argument(
        "--channel", choices=["sms", "push", "both"], default="both",
        help="Which channel to target (default: both)",
    )
    parser.add_argument(
        "--status", choices=["ready", "any"], default="any",
        help="'ready' = Ready to Code only; 'any' = all tasks (default: any)",
    )
    parser.add_argument(
        "--task-gid", metavar="GID",
        help="Clear a specific task by GID (ignores --channel/--status filters)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be cleared without making changes",
    )
    args = parser.parse_args()

    dry = args.dry_run
    prefix = "[DRY RUN] " if dry else ""

    # --- Single task mode ---
    if args.task_gid:
        task = _asana_request("GET", f"tasks/{args.task_gid}",
                               params={"opt_fields": "name,gid,custom_fields"})
        if not task:
            sys.exit(f"Could not fetch task {args.task_gid}")
        link = _get_text_value(task, FIELD_BRAZE_LINK)
        name = task.get("name", args.task_gid)
        if not link:
            print(f"Task '{name}' has no Braze link — nothing to clear.")
            return
        print(f"{prefix}Clear '{name}' → {link}")
        if not dry:
            ok = clear_braze_link(args.task_gid)
            print("  ✓ cleared" if ok else "  ✗ failed")
        return

    # --- Bulk mode ---
    if args.channel == "both":
        channel_gids = [CHANNEL_OPTIONS["sms"], CHANNEL_OPTIONS["push"]]
    else:
        channel_gids = [CHANNEL_OPTIONS[args.channel]]

    status_gid = STATUS_READY_TO_CODE if args.status == "ready" else None

    print(f"Searching Asana tasks (channel={args.channel}, status={args.status})...")
    tasks = search_tasks(channel_gids, status_gid)

    # Filter to only tasks that have a Braze link set
    tasks_with_link = [
        t for t in tasks
        if _get_text_value(t, FIELD_BRAZE_LINK)
    ]

    if not tasks_with_link:
        print("No tasks found with a Braze link set.")
        return

    print(f"Found {len(tasks_with_link)} task(s) with Braze links:\n")
    for task in tasks_with_link:
        name = task.get("name", task["gid"])
        link = _get_text_value(task, FIELD_BRAZE_LINK)
        print(f"  {prefix}{name}")
        print(f"    {link}")
        if not dry:
            ok = clear_braze_link(task["gid"])
            print(f"    → {'✓ cleared' if ok else '✗ failed'}")

    if dry:
        print(f"\n{len(tasks_with_link)} task(s) would be cleared. Re-run without --dry-run to apply.")
    else:
        print(f"\nDone. {len(tasks_with_link)} task(s) cleared.")


if __name__ == "__main__":
    main()

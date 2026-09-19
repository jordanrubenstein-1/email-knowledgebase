#!/usr/bin/env python3
"""Fix Asana tasks that have literal \\n in their description instead of real newlines.

Root cause: Claude Haiku occasionally outputs literal \\n as two characters in
structured text responses rather than actual newlines. Those two-char sequences
end up stored in the Asana notes field verbatim.

This script:
  1. Paginates through all tasks in the Master CRM project
  2. Finds any task whose notes contain the two-char sequence backslash + n
  3. Replaces them with real newlines and updates the task

Usage:
    uv run python scripts/fix_asana_literal_newlines.py --dry-run   # preview
    uv run python scripts/fix_asana_literal_newlines.py             # apply
"""

import argparse
import os
import time

import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"  # Master CRM (Email & SMS)
ASANA_WORKSPACE_GID = "5257710284167"
TODAY = "2026-05-12"
YESTERDAY = "2026-05-11"  # due_on.after is exclusive, so this gives today+

# The two-character sequence we're hunting for: backslash + n
LITERAL_N = "\\n"


def asana_headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        raise EnvironmentError("ASANA_ACCESS_TOKEN not set in .env")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(endpoint: str, params: dict) -> tuple[list, str | None]:
    """GET with rate-limit retry. Returns (data list, next_page offset or None)."""
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=asana_headers(), params=params)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.get(url, headers=asana_headers(), params=params)
    if resp.status_code != 200:
        print(f"  GET error {resp.status_code}: {resp.text[:200]}")
        return [], None
    body = resp.json()
    next_offset = (body.get("next_page") or {}).get("offset")
    return body.get("data", []), next_offset


def _put(endpoint: str, payload: dict) -> bool:
    """PUT with rate-limit retry. Returns True on success."""
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.put(url, headers=asana_headers(), json=payload)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.put(url, headers=asana_headers(), json=payload)
    return resp.status_code in (200, 201)


def fetch_tasks_from_today() -> list[dict]:
    """Fetch tasks due today or later from the project via the search endpoint."""
    params = {
        "projects.any": ASANA_PROJECT_GID,
        "due_on.after": YESTERDAY,  # exclusive — returns tasks due on TODAY or later
        "opt_fields": "gid,name,notes",
        "limit": 100,
    }
    tasks, _ = _get(f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search", params)
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix literal \\n in Asana task descriptions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show affected tasks without making changes",
    )
    args = parser.parse_args()

    print(f"Scanning Master CRM tasks due {TODAY} or later for literal \\n in descriptions...\n")

    all_tasks = fetch_tasks_from_today()
    print(f"Total tasks scanned: {len(all_tasks)}\n")

    affected = [
        t for t in all_tasks
        if t.get("notes") and LITERAL_N in t["notes"]
    ]

    if not affected:
        print("No tasks found with literal \\n in description. Nothing to fix!")
        return

    print(f"Found {len(affected)} task(s) with literal \\n in description:\n")
    for t in affected:
        count = t["notes"].count(LITERAL_N)
        print(f"  {t['gid']}  {t['name'][:70]}  ({count} instance{'s' if count != 1 else ''})")

    if args.dry_run:
        print("\nDRY RUN — no changes made. Run without --dry-run to apply fixes.")
        return

    print(f"\nApplying fixes to {len(affected)} task(s)...")
    fixed = failed = 0

    for t in affected:
        corrected = t["notes"].replace(LITERAL_N, "\n")
        ok = _put(f"tasks/{t['gid']}", {"data": {"notes": corrected}})
        if ok:
            print(f"  ✓  {t['name'][:70]}")
            fixed += 1
        else:
            print(f"  ✗  FAILED: {t['name'][:70]}")
            failed += 1
        time.sleep(0.3)

    print(f"\nDone. Fixed: {fixed}, Failed: {failed}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backfill bold formatting for copy fields in CZ designed email Asana task briefs.

Targets tasks with due_on >= 2026-06-11, Brand=CZ, Channel=Email that contain
an auto-generated Body Copy section. Applies <strong> tags to copy field values
in-place using regex substitution. Idempotent — skips tasks already bolded.

Usage:
    uv run python scripts/braze_automation/backfill_cz_brief_bold.py [--dry-run] [--limit N]
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
WORKSPACE_GID = "5257710284167"
PROJECT_GID = "1207522423363072"  # Master CRM (Email & SMS)

CZ_BRAND_GID = "1207553690167887"
EMAIL_CHANNEL_GID = "1207562370794989"
BRAND_FIELD_GID = "1207522425689880"
CHANNEL_FIELD_GID = "1207562370794988"

CUTOFF_DATE = "2026-06-10"  # due_on.after = tasks due 2026-06-11 and later

# Copy field labels whose values should be bolded (longest first for regex alternation)
COPY_LABELS = [
    "Featured product", "Photo credit",
    "Hero CTA", "Body CTA", "Final CTA", "Kicker CTA",
    "Body HED", "Body DEK",
    "Sale Lock-up", "Sale copy",
    "CTA button",
    "Eyebrow", "HED", "DEK", "CTA", "Name", "SL", "PH",
]
_label_pat = "|".join(re.escape(l) for l in COPY_LABELS)
# Also match: "Category Block N CTA", "Section N DEK/CTA/HED/Eyebrow", "Room N DEK/CTA/HED/Eyebrow"
_label_pat = (
    f"(?:{_label_pat}"
    r"|Category Block \d+ CTA"
    r"|(?:Section|Room) \d+ (?:DEK|CTA|HED|Eyebrow)"
    ")"
)
BOLD_RE = re.compile(rf"<li>({_label_pat}): (?!<strong>)([^<]+)(</li>)")

# Bare sale link farm copy (tasks created before the "Sale copy:" prefix was added).
# Matches the first non-Link <li> immediately after "Sale link farm header".
FARM_SALE_RE = re.compile(
    r"(Sale link farm header[^<]*</li><ul><li>)(?!<strong>)(?!Sale copy:)(?!Link:)([^<]+)(</li>)"
)


def _get_token() -> str:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(endpoint: str, params: dict = None) -> Optional[dict]:
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.get(url, headers=_headers(), params=params)
    if resp.status_code != 200:
        print(f"  GET error {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json()


def _put(endpoint: str, data: dict) -> bool:
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.put(url, headers=_headers(), json={"data": data})
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.put(url, headers=_headers(), json={"data": data})
    if resp.status_code not in (200, 201):
        print(f"  PUT error {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def fetch_tasks() -> list:
    tasks = []
    params = {
        "project": PROJECT_GID,
        f"custom_fields.{BRAND_FIELD_GID}.value": CZ_BRAND_GID,
        f"custom_fields.{CHANNEL_FIELD_GID}.value": EMAIL_CHANNEL_GID,
        "due_on.after": CUTOFF_DATE,
        "opt_fields": "gid,name,due_on,html_notes",
        "limit": 100,
    }
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        result = _get(f"workspaces/{WORKSPACE_GID}/tasks/search", params)
        if not result:
            break
        batch = result.get("data", [])
        tasks.extend(batch)
        next_page = result.get("next_page")
        if not next_page:
            break
        offset = next_page.get("offset")
    return tasks


def apply_bold(html: str) -> str:
    html = BOLD_RE.sub(r"<li>\1: <strong>\2</strong>\3", html)
    html = FARM_SALE_RE.sub(r"\1<strong>\2</strong>\3", html)
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, help="Max tasks to process")
    args = parser.parse_args()

    print(f"Fetching CZ email tasks due 2026-06-11+...")
    tasks = fetch_tasks()
    print(f"  Found {len(tasks)} tasks total")

    if args.limit:
        tasks = tasks[: args.limit]

    updated = skipped_no_body = skipped_already_bold = errors = 0

    for task in tasks:
        gid = task["gid"]
        name = task.get("name", "")
        due = task.get("due_on", "")
        html = task.get("html_notes") or ""

        if "Body Copy" not in html:
            skipped_no_body += 1
            continue

        new_html = apply_bold(html)

        if new_html == html:
            skipped_already_bold += 1
            continue

        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"  {prefix}Updating: {name} (due {due})")

        if not args.dry_run:
            ok = _put(f"tasks/{gid}", {"html_notes": new_html})
            if ok:
                updated += 1
            else:
                errors += 1
            time.sleep(0.3)
        else:
            updated += 1

    print(
        f"\nDone."
        f" Updated: {updated}"
        f" | Already bold: {skipped_already_bold}"
        f" | No body copy (skipped): {skipped_no_body}"
        + (f" | Errors: {errors}" if errors else "")
        + (" (dry-run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()

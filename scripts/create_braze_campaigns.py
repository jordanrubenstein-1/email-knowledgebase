#!/usr/bin/env python3
"""
Create Braze campaign shells from Asana tasks marked "Ready to Code".

Finds tasks in the Master CRM project with "Ready to Code" status, creates
a Braze campaign shell (name + subject + preheader), and writes the Braze
campaign ID and dashboard link back to the Asana task.

Usage:
    # Preview what would be created (no API calls)
    uv run python scripts/create_braze_campaigns.py --dry-run

    # Create campaigns for all "Ready to Code" tasks
    uv run python scripts/create_braze_campaigns.py

    # Filter to one brand
    uv run python scripts/create_braze_campaigns.py --brand HAV

    # Re-process tasks that already have a braze_campaign_id
    uv run python scripts/create_braze_campaigns.py --force
"""

import os
import sys
import argparse
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv
import requests

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Import Braze API helpers
sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request
from import_braze import init_config, normalize_brand

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"
BRAZE_DASHBOARD_BASE = os.environ.get(
    "BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com"
).rstrip("/")

# Asana custom field GIDs
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_SUBJECT_LINE = "1207522425689914"
FIELD_PRE_HEADER = "1207522425689916"
FIELD_SEGMENT = "1211927654349290"
FIELD_AUDIENCE = "1207522425689896"
FIELD_SEND_TIME = "1212524397761931"
FIELD_BRAZE_LINK = "1210710306792280"
FIELD_BRAZE_CAMPAIGN_ID = "1210955430688137"

# Task Status enum values
STATUS_READY_TO_CODE = "1209995669275789"

# Brand enum GID → brand code
BRAND_OPTIONS = {
    "HAV": "1207522425689881",
    "CZ": "1207553690167887",
    "ID": "1207522425689882",
    "BUR": "1208572919795447",
    "TI": "1207522425689883",
    "STF": "1207881071843537",
    "TRADE": "1208130746998739",
}
BRAND_GID_TO_CODE = {v: k for k, v in BRAND_OPTIONS.items()}

# Channel enum GID → channel name
CHANNEL_OPTIONS = {
    "email": "1207562370794989",
    "sms": "1207562370794990",
    "push": "1207562370794991",
}
CHANNEL_GID_TO_NAME = {v: k for k, v in CHANNEL_OPTIONS.items()}


# ---------------------------------------------------------------------------
# Asana API helpers
# ---------------------------------------------------------------------------

def get_asana_token() -> str:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return token


def asana_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_asana_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def asana_request(method: str, endpoint: str, json_data: Optional[dict] = None,
                  params: Optional[dict] = None) -> Optional[Any]:
    """Make an Asana API request with rate-limit handling."""
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=asana_headers(),
                            json=json_data, params=params)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {retry_after}s...")
        time.sleep(retry_after)
        resp = requests.request(method, url, headers=asana_headers(),
                                json=json_data, params=params)

    if resp.status_code not in (200, 201):
        print(f"  Asana error {resp.status_code}: {resp.text[:300]}")
        return None

    return resp.json().get("data")


# ---------------------------------------------------------------------------
# Asana task parsing
# ---------------------------------------------------------------------------

def get_custom_field(task: Dict, field_gid: str) -> Optional[Dict]:
    """Get a custom field dict from a task by its GID."""
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            return cf
    return None


def get_enum_value_gid(task: Dict, field_gid: str) -> Optional[str]:
    """Get the GID of the selected enum value for a custom field."""
    cf = get_custom_field(task, field_gid)
    if cf and cf.get("enum_value"):
        return cf["enum_value"].get("gid")
    return None


def get_enum_value_name(task: Dict, field_gid: str) -> Optional[str]:
    """Get the name of the selected enum value for a custom field."""
    cf = get_custom_field(task, field_gid)
    if cf and cf.get("enum_value"):
        return cf["enum_value"].get("name")
    return None


def get_text_value(task: Dict, field_gid: str) -> Optional[str]:
    """Get the text/display value for a custom field."""
    cf = get_custom_field(task, field_gid)
    if not cf:
        return None
    # Text fields use text_value, others use display_value
    return cf.get("text_value") or cf.get("display_value")


def parse_task(task: Dict) -> Optional[Dict[str, Any]]:
    """Parse an Asana task into a structured record for Braze campaign creation.

    Returns None if the task is missing required fields (brand, channel).
    """
    task_gid = task.get("gid")
    task_name = task.get("name", "")
    due_on = task.get("due_on")

    # Brand
    brand_gid = get_enum_value_gid(task, FIELD_BRAND)
    brand_code = BRAND_GID_TO_CODE.get(brand_gid) if brand_gid else None
    if not brand_code:
        return None

    # Channel
    channel_gid = get_enum_value_gid(task, FIELD_CHANNEL)
    channel = CHANNEL_GID_TO_NAME.get(channel_gid) if channel_gid else None
    if not channel:
        return None

    # Subject line and preheader
    subject_line = get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = get_text_value(task, FIELD_PRE_HEADER) or ""

    # Segment and audience
    segment = get_enum_value_name(task, FIELD_SEGMENT)
    audience = get_enum_value_name(task, FIELD_AUDIENCE)

    # Send time
    send_time = get_text_value(task, FIELD_SEND_TIME)

    # Existing Braze campaign ID (to check if already processed)
    braze_campaign_id = get_text_value(task, FIELD_BRAZE_CAMPAIGN_ID)

    return {
        "gid": task_gid,
        "name": task_name,
        "due_on": due_on,
        "brand": brand_code,
        "channel": channel,
        "subject_line": subject_line,
        "preheader": preheader,
        "segment": segment,
        "audience": audience,
        "send_time": send_time,
        "braze_campaign_id": braze_campaign_id,
    }


# ---------------------------------------------------------------------------
# Fetch "Ready to Code" tasks from Asana
# ---------------------------------------------------------------------------

def fetch_ready_to_code_tasks(brand_filter: Optional[str] = None) -> List[Dict]:
    """Fetch tasks with 'Ready to Code' status from Asana.

    Args:
        brand_filter: Optional brand code to filter results.

    Returns:
        List of parsed task records.
    """
    # Asana search API uses dot notation for nested params
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        "opt_fields": ",".join([
            "name", "due_on", "completed",
            "custom_fields", "custom_fields.gid",
            "custom_fields.enum_value", "custom_fields.enum_value.gid",
            "custom_fields.enum_value.name",
            "custom_fields.text_value", "custom_fields.display_value",
        ]),
        "limit": 100,
    }

    # Add brand filter at API level if specified
    if brand_filter:
        brand_gid = BRAND_OPTIONS.get(brand_filter.upper())
        if brand_gid:
            params[f"custom_fields.{FIELD_BRAND}.value"] = brand_gid

    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    tasks_data = asana_request("GET", endpoint, params=params)

    if not tasks_data:
        return []

    results = []
    for task in tasks_data:
        # Skip completed tasks
        if task.get("completed"):
            continue
        record = parse_task(task)
        if record:
            results.append(record)

    return results


# ---------------------------------------------------------------------------
# Braze campaign creation
# ---------------------------------------------------------------------------

def create_braze_campaign_shell(record: Dict[str, Any], dry_run: bool = False) -> Optional[str]:
    """Create a Braze campaign shell from task metadata.

    Args:
        record: Parsed task record.
        dry_run: If True, print what would be created without making API calls.

    Returns:
        Braze campaign ID if successful, None otherwise.
    """
    brand = record["brand"]
    channel = record["channel"]
    name = record["name"]

    # Validate campaign name against naming convention
    try:
        from scripts.utils.campaign_name import validate_campaign_name
        is_valid, issues = validate_campaign_name(name)
        if not is_valid:
            print(f"  ⚠ Name may not follow convention: {'; '.join(issues)}")
    except ImportError:
        pass  # Utility not available; skip validation

    if dry_run:
        print(f"  [DRY RUN] Would create Braze {channel} campaign: {name}")
        if record["subject_line"]:
            print(f"    Subject: {record['subject_line']}")
        if record["preheader"]:
            print(f"    Preheader: {record['preheader']}")
        if record["segment"]:
            print(f"    Segment: {record['segment']}")
        if record["send_time"]:
            print(f"    Send time: {record['send_time']}")
        return "dry-run-id"

    # Initialize Braze config for this brand
    init_config(brand)

    # Build campaign payload
    campaign_data = {
        "name": name,
        "description": f"Created from Asana task {record['gid']}",
    }

    # Add message configuration based on channel
    if channel == "email":
        messages = {"email": {}}
        if record["subject_line"]:
            messages["email"]["subject"] = record["subject_line"]
        if record["preheader"]:
            messages["email"]["preheader"] = record["preheader"]
        campaign_data["messages"] = messages
    elif channel == "sms":
        campaign_data["messages"] = {"sms": {}}
    elif channel == "push":
        campaign_data["messages"] = {"push": {}}

    response_data, error = braze_post_request("campaigns/create", campaign_data, brand)

    if error:
        print(f"  ✗ Braze error: {error}")
        return None

    campaign_id = None
    if response_data:
        campaign_id = response_data.get("campaign_id") or response_data.get("id")

    if not campaign_id:
        print(f"  ✗ Unexpected Braze response: {response_data}")
        return None

    return campaign_id


def update_asana_with_braze_link(task_gid: str, campaign_id: str, dry_run: bool = False) -> bool:
    """Write the Braze campaign ID and dashboard link back to the Asana task.

    Args:
        task_gid: Asana task GID.
        campaign_id: Braze campaign ID.
        dry_run: If True, skip the actual update.

    Returns:
        True if successful, False otherwise.
    """
    dashboard_link = f"{BRAZE_DASHBOARD_BASE}/campaigns/{campaign_id}"

    if dry_run:
        print(f"  [DRY RUN] Would update Asana task {task_gid}:")
        print(f"    braze_campaign_id: {campaign_id}")
        print(f"    Braze Campaign Link: {dashboard_link}")
        return True

    payload = {
        "data": {
            "custom_fields": {
                FIELD_BRAZE_CAMPAIGN_ID: campaign_id,
                FIELD_BRAZE_LINK: dashboard_link,
            }
        }
    }

    result = asana_request("PUT", f"tasks/{task_gid}", json_data=payload)
    return result is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Create Braze campaign shells from Asana 'Ready to Code' tasks."
    )
    parser.add_argument("--brand", type=str, help="Filter to one brand (e.g., HAV, CZ, STF)")
    parser.add_argument("--task", type=str, help="Process a single Asana task GID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making API calls")
    parser.add_argument("--force", action="store_true",
                        help="Re-process tasks that already have a braze_campaign_id")
    args = parser.parse_args()

    brand_filter = normalize_brand(args.brand) if args.brand else None

    print("Scanning Asana for 'Ready to Code' tasks...")
    tasks = fetch_ready_to_code_tasks(brand_filter)

    # Filter to a single task if --task is specified
    if args.task:
        tasks = [t for t in tasks if t["gid"] == args.task]
        if not tasks:
            print(f"Task {args.task} not found or not in 'Ready to Code' status.")
            return

    if not tasks:
        print("No 'Ready to Code' tasks found.")
        return

    # Filter out already-processed tasks (unless --force)
    if not args.force:
        original_count = len(tasks)
        tasks = [t for t in tasks if not t["braze_campaign_id"]]
        skipped = original_count - len(tasks)
        if skipped:
            print(f"Skipping {skipped} task(s) that already have a Braze campaign ID (use --force to re-process).")

    if not tasks:
        print("All matching tasks already have Braze campaigns.")
        return

    print(f"Found {len(tasks)} task(s) to process.\n")

    created = 0
    skipped = 0
    failed = 0

    for i, record in enumerate(tasks, 1):
        label = f"[{i}/{len(tasks)}] {record['brand']}: {record['name']} ({record['channel']})"
        print(label)

        # Warn if email is missing subject line
        if record["channel"] == "email" and not record["subject_line"]:
            print(f"  ⚠ Warning: no subject line set")

        # Create Braze campaign shell
        campaign_id = create_braze_campaign_shell(record, dry_run=args.dry_run)

        if not campaign_id:
            failed += 1
            continue

        if not args.dry_run:
            print(f"  ✓ Braze campaign created: {campaign_id}")

        # Write back to Asana
        success = update_asana_with_braze_link(record["gid"], campaign_id, dry_run=args.dry_run)

        if success:
            if not args.dry_run:
                print(f"  ✓ Asana updated with campaign link")
            created += 1
        else:
            print(f"  ✗ Failed to update Asana task")
            failed += 1

        print()

    # Summary
    print(f"Summary: {created} created, {skipped} skipped, {failed} failed")
    if args.dry_run:
        print("(dry run — no changes were made)")


if __name__ == "__main__":
    main()

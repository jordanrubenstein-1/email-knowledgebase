#!/usr/bin/env python3
"""
Search Asana for SMS and Push notification tasks that are ready to code.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests
from datetime import datetime

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
PROJECT_GID = "1207522423363072"  # Master CRM (Email & SMS)

def get_access_token():
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return token

def asana_request(endpoint, params=None):
    """Make a request to Asana API. Returns (data, next_page_params)."""
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    url = f"{ASANA_BASE_URL}/{endpoint}"
    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
        return None, None

    result = response.json()
    next_page = result.get("next_page")
    return result.get("data"), next_page

def get_project_tasks(project_gid, due_on_after=None):
    """Get all tasks in a project with optional date filtering."""
    tasks = []
    params = {
        "opt_fields": "name,gid,due_on,completed,completed_at,assignee.name,custom_fields.name,custom_fields.display_value,custom_fields.enum_value.name",
        "limit": 100
    }

    # Add date filter if provided
    if due_on_after:
        params["completed_since"] = "now"  # Only get uncompleted or recently completed

    while True:
        data, next_page = asana_request(f"projects/{project_gid}/tasks", params)
        if data:
            tasks.extend(data)

        if not next_page or not next_page.get("offset"):
            break

        params["offset"] = next_page["offset"]

    return tasks

def filter_tasks(tasks, keywords=None, due_after=None):
    """Filter tasks by keywords in name and due date."""
    filtered = []

    for task in tasks:
        # Skip completed tasks
        if task.get("completed"):
            continue

        # Check due date
        due_on = task.get("due_on")
        if due_after and due_on:
            try:
                task_date = datetime.strptime(due_on, "%Y-%m-%d").date()
                if task_date <= due_after:
                    continue
            except:
                pass

        # Check keywords in task name
        task_name = task.get("name", "").upper()
        if keywords:
            if any(kw.upper() in task_name for kw in keywords):
                filtered.append(task)
        else:
            filtered.append(task)

    return filtered

def check_ready_status(task):
    """Check if task has a 'ready to code' status in custom fields."""
    custom_fields = task.get("custom_fields", [])

    ready_statuses = [
        "ready to code",
        "ready to build",
        "ready for dev",
        "ready for development",
        "ready",
        "to do",
        "in progress"
    ]

    for cf in custom_fields:
        cf_name = (cf.get("name") or "").lower()
        cf_value = (cf.get("display_value") or "").lower()
        enum_value = cf.get("enum_value", {})
        enum_name = (enum_value.get("name") or "").lower() if enum_value else ""

        # Check if this is a status field
        if "status" in cf_name or "stage" in cf_name or "state" in cf_name:
            # Check if value matches ready status
            if any(status in cf_value for status in ready_statuses) or \
               any(status in enum_name for status in ready_statuses):
                return True, cf_value or enum_name

    return False, None

def get_custom_field_value(task, field_keywords):
    """Get value of a custom field matching keywords."""
    custom_fields = task.get("custom_fields", [])

    for cf in custom_fields:
        cf_name = (cf.get("name") or "").lower()
        if any(kw.lower() in cf_name for kw in field_keywords):
            value = cf.get("display_value")
            if not value:
                enum_value = cf.get("enum_value")
                if enum_value:
                    value = enum_value.get("name")
            return value

    return None

def main():
    print("Searching for SMS and Push notification tasks ready to code...")
    print(f"Project: Master CRM (Email & SMS) - {PROJECT_GID}")
    print(f"Date filter: Due after 2026-02-14")
    print("=" * 80)
    print()

    # Get all tasks from the project
    print("Fetching tasks from Asana...")
    all_tasks = get_project_tasks(PROJECT_GID)
    print(f"Found {len(all_tasks)} total tasks in project")
    print()

    # Filter for SMS and Push tasks
    today = datetime.strptime("2026-02-14", "%Y-%m-%d").date()

    print("Filtering for SMS tasks...")
    sms_tasks = filter_tasks(all_tasks, keywords=["SMS"], due_after=today)
    print(f"Found {len(sms_tasks)} SMS tasks with future due dates")
    print()

    print("Filtering for Push tasks...")
    push_tasks = filter_tasks(all_tasks, keywords=["PUSH"], due_after=today)
    print(f"Found {len(push_tasks)} Push tasks with future due dates")
    print()

    # Combine and filter for ready status
    candidate_tasks = sms_tasks + push_tasks
    ready_tasks = []

    print("Checking which tasks are ready to code...")
    for task in candidate_tasks:
        is_ready, status_value = check_ready_status(task)
        if is_ready:
            ready_tasks.append((task, status_value))

    print(f"Found {len(ready_tasks)} tasks ready to code")
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    if not ready_tasks:
        print("No SMS or Push tasks found that are:")
        print("  - Ready to code (based on status fields)")
        print("  - Not completed")
        print("  - Due after 2026-02-14")
        print()
        print("Showing ALL uncompleted SMS/Push tasks with future due dates instead:")
        print()

        for task in candidate_tasks:
            name = task.get("name", "Unnamed")
            gid = task.get("gid")
            due_on = task.get("due_on", "No due date")
            assignee_data = task.get("assignee")
            assignee = assignee_data.get("name", "Unassigned") if assignee_data else "Unassigned"

            # Get brand and status
            brand = get_custom_field_value(task, ["brand"]) or "Unknown"
            status = get_custom_field_value(task, ["status", "stage", "state"]) or "Unknown"
            channel = get_custom_field_value(task, ["channel", "type"]) or "Unknown"

            print(f"Task: {name}")
            print(f"  GID: {gid}")
            print(f"  Due: {due_on}")
            print(f"  Brand: {brand}")
            print(f"  Status: {status}")
            print(f"  Channel: {channel}")
            print(f"  Assignee: {assignee}")
            print()
    else:
        for task, status_value in ready_tasks:
            name = task.get("name", "Unnamed")
            gid = task.get("gid")
            due_on = task.get("due_on", "No due date")
            assignee_data = task.get("assignee")
            assignee = assignee_data.get("name", "Unassigned") if assignee_data else "Unassigned"

            # Get brand and channel
            brand = get_custom_field_value(task, ["brand"]) or "Unknown"
            channel = get_custom_field_value(task, ["channel", "type"]) or "Unknown"

            print(f"Task: {name}")
            print(f"  GID: {gid}")
            print(f"  Due: {due_on}")
            print(f"  Brand: {brand}")
            print(f"  Status: {status_value}")
            print(f"  Channel: {channel}")
            print(f"  Assignee: {assignee}")
            print(f"  URL: https://app.asana.com/0/{PROJECT_GID}/{gid}")
            print()

    print("=" * 80)
    print(f"Summary: {len(ready_tasks)} ready tasks, {len(candidate_tasks)} total SMS/Push tasks")

if __name__ == "__main__":
    main()

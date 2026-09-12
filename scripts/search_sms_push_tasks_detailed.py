#!/usr/bin/env python3
"""
Search Asana for SMS and Push notification tasks - detailed view with all statuses.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests
from datetime import datetime
from collections import defaultdict

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

def get_project_tasks(project_gid):
    """Get all tasks in a project."""
    tasks = []
    params = {
        "opt_fields": "name,gid,due_on,completed,completed_at,assignee.name,custom_fields.name,custom_fields.display_value,custom_fields.enum_value.name",
        "limit": 100
    }

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
    print("Searching for SMS and Push notification tasks (all uncompleted with future due dates)...")
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

    # Combine
    candidate_tasks = sms_tasks + push_tasks

    # Group by status
    tasks_by_status = defaultdict(list)

    for task in candidate_tasks:
        status = get_custom_field_value(task, ["status", "stage", "state"]) or "No Status"
        tasks_by_status[status].append(task)

    print("=" * 80)
    print("RESULTS - Grouped by Status")
    print("=" * 80)
    print()

    # Sort statuses to show "ready" ones first
    ready_keywords = ["ready", "to do", "in progress", "in dev"]
    sorted_statuses = sorted(tasks_by_status.keys(),
                            key=lambda s: (not any(kw in s.lower() for kw in ready_keywords), s))

    for status in sorted_statuses:
        tasks = tasks_by_status[status]
        print(f"Status: {status} ({len(tasks)} tasks)")
        print("-" * 80)

        for task in tasks:
            name = task.get("name", "Unnamed")
            gid = task.get("gid")
            due_on = task.get("due_on", "No due date")
            assignee_data = task.get("assignee")
            assignee = assignee_data.get("name", "Unassigned") if assignee_data else "Unassigned"

            # Get brand and channel
            brand = get_custom_field_value(task, ["brand"]) or "Unknown"
            channel = get_custom_field_value(task, ["channel", "type"]) or "Unknown"

            print(f"  Task: {name}")
            print(f"    GID: {gid}")
            print(f"    Due: {due_on}")
            print(f"    Brand: {brand}")
            print(f"    Channel: {channel}")
            print(f"    Assignee: {assignee}")
            print(f"    URL: https://app.asana.com/0/{PROJECT_GID}/{gid}")
            print()

    print("=" * 80)
    print(f"Summary: {len(candidate_tasks)} total uncompleted SMS/Push tasks with future due dates")
    print()
    print("Status breakdown:")
    for status in sorted_statuses:
        print(f"  {status}: {len(tasks_by_status[status])} tasks")

if __name__ == "__main__":
    main()

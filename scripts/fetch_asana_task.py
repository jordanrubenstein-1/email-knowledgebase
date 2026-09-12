#!/usr/bin/env python3
"""
Fetch a single Asana task by GID with full details: name, notes, due date,
custom fields, section (Segment), subtasks, attachments.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
WORKSPACE_GID = "5257710284167"


def get_access_token():
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return token


def asana_request(endpoint, params=None, method="GET"):
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    url = f"{ASANA_BASE_URL}/{endpoint}"
    response = requests.request(method, url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
        return None, None
    result = response.json()
    return result.get("data"), result.get("next_page")


def get_task(task_gid):
    """Get task with full opt_fields including section (Segment) and custom fields."""
    data, _ = asana_request(
        f"tasks/{task_gid}",
        {
            "opt_fields": (
                "name,notes,due_on,start_on,completed,completed_at,created_at,modified_at,"
                "assignee.name,assignee.email,tags.name,tags.gid,"
                "custom_fields,custom_fields.name,custom_fields.display_value,"
                "custom_fields.enum_value.name,custom_fields.type,"
                "memberships,memberships.section,memberships.section.name,memberships.project.name"
            )
        },
    )
    return data


def get_subtasks(task_gid):
    """Get all subtasks for a task."""
    tasks = []
    params = {
        "opt_fields": "name,notes,due_on,completed,completed_at,custom_fields.name,custom_fields.display_value,custom_fields.enum_value.name",
        "limit": 100,
    }
    while True:
        data, next_page = asana_request(f"tasks/{task_gid}/subtasks", params)
        if data:
            tasks.extend(data)
        if not next_page or not next_page.get("offset"):
            break
        params["offset"] = next_page["offset"]
    return tasks


def get_attachments(task_gid):
    """Get attachments for a task (parent is the task)."""
    data, _ = asana_request(
        "attachments",
        {"parent": task_gid, "opt_fields": "name,download_url,view_url,resource_subtype,created_at"},
    )
    return data or []


def get_stories(task_gid):
    """Get stories (comments/activity) for a task."""
    stories = []
    params = {
        "opt_fields": "type,created_at,created_by.name,created_by.email,text,html_text",
        "limit": 100,
    }
    while True:
        data, next_page = asana_request(f"tasks/{task_gid}/stories", params)
        if data:
            stories.extend(data)
        if not next_page or not next_page.get("offset"):
            break
        params["offset"] = next_page["offset"]
    return stories


def main():
    task_gid = sys.argv[1] if len(sys.argv) > 1 else "1213104067064244"
    print(f"Fetching Asana task GID: {task_gid} (workspace {WORKSPACE_GID})\n")

    task = get_task(task_gid)
    if not task:
        print("Failed to fetch task.")
        sys.exit(1)

    subtasks = get_subtasks(task_gid)
    attachments = get_attachments(task_gid)
    stories = get_stories(task_gid)

    # Section / Segment from memberships
    sections = []
    if task.get("memberships"):
        for m in task["memberships"]:
            sec = m.get("section")
            if sec:
                sections.append(sec.get("name") or sec.get("gid"))
    segment = sections[0] if sections else None

    # Output full details
    out = {
        "gid": task.get("gid"),
        "name": task.get("name"),
        "notes": task.get("notes") or "",
        "due_on": task.get("due_on"),
        "start_on": task.get("start_on"),
        "completed": task.get("completed"),
        "completed_at": task.get("completed_at"),
        "created_at": task.get("created_at"),
        "modified_at": task.get("modified_at"),
        "assignee": (
            {"name": task["assignee"].get("name"), "email": task["assignee"].get("email")}
            if task.get("assignee")
            else None
        ),
        "tags": [t.get("name") for t in (task.get("tags") or [])],
        "segment_section": segment,
        "memberships": [
            {
                "project": m.get("project", {}).get("name"),
                "section": m.get("section", {}).get("name") if m.get("section") else None,
            }
            for m in (task.get("memberships") or [])
        ],
        "custom_fields": [],
        "subtasks": [],
        "attachments": [],
        "stories": [],
    }

    for cf in task.get("custom_fields") or []:
        val = cf.get("display_value") or (cf.get("enum_value") or {}).get("name")
        out["custom_fields"].append(
            {"name": cf.get("name"), "value": val, "type": cf.get("type")}
        )

    for st in subtasks:
        st_cfs = []
        for cf in st.get("custom_fields") or []:
            val = cf.get("display_value") or (cf.get("enum_value") or {}).get("name")
            st_cfs.append({"name": cf.get("name"), "value": val})
        out["subtasks"].append(
            {
                "gid": st.get("gid"),
                "name": st.get("name"),
                "notes": (st.get("notes") or "")[:500],
                "due_on": st.get("due_on"),
                "completed": st.get("completed"),
                "custom_fields": st_cfs,
            }
        )

    for att in attachments:
        out["attachments"].append(
            {
                "name": att.get("name"),
                "download_url": att.get("download_url"),
                "view_url": att.get("view_url"),
                "resource_subtype": att.get("resource_subtype"),
                "created_at": att.get("created_at"),
            }
        )

    for s in stories:
        out["stories"].append(
            {
                "type": s.get("type"),
                "created_at": s.get("created_at"),
                "created_by": (
                    {"name": s["created_by"].get("name"), "email": s["created_by"].get("email")}
                    if s.get("created_by")
                    else None
                ),
                "text": s.get("text"),
                "html_text": (s.get("html_text") or "")[:2000],
            }
        )

    # Pretty-print to stdout
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    main()

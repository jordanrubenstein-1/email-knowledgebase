#!/usr/bin/env python3
"""
Import campaign planning data from Asana.

This script pulls tasks from an Asana project and exports them
in a format that can be correlated with Braze campaign data.

Usage:
    # First, copy .env.example to .env and fill in your token
    uv run python scripts/import_asana.py --project "Email Calendar 2024"

Options:
    --project NAME    Asana project name to import from
    --workspace NAME  Workspace name (if you have multiple)
    --dry-run         Print what would be imported without writing
    --list-projects   List available projects and exit
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import requests
import yaml

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"

def get_access_token():
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set")
        print("Copy .env.example to .env and fill in your token")
        print()
        print("To get a token:")
        print("1. Go to https://app.asana.com/0/my-apps")
        print("2. Create a new Personal Access Token")
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
        print(f"Error {response.status_code}: {response.text}")
        return None, None

    result = response.json()
    next_page = result.get("next_page")
    return result.get("data"), next_page

def get_workspaces():
    """Get list of workspaces the user has access to."""
    data, _ = asana_request("workspaces")
    return data

def get_projects(workspace_gid):
    """Get projects in a workspace."""
    data, _ = asana_request(f"workspaces/{workspace_gid}/projects", {
        "opt_fields": "name,created_at,modified_at"
    })
    return data

def find_project(workspace_gid, project_name):
    """Find a project by name."""
    projects = get_projects(workspace_gid)
    if not projects:
        return None

    # Exact match first
    for p in projects:
        if p["name"].lower() == project_name.lower():
            return p

    # Partial match
    for p in projects:
        if project_name.lower() in p["name"].lower():
            return p

    return None

def get_tasks(project_gid):
    """Get all tasks from a project with relevant fields."""
    tasks = []
    params = {
        "opt_fields": "name,notes,due_on,start_on,completed,completed_at,tags,tags.name,custom_fields,custom_fields.name,custom_fields.display_value,assignee,assignee.name,created_at,modified_at,memberships.section,memberships.section.name",
        "limit": 100
    }

    while True:
        data, next_page = asana_request(f"projects/{project_gid}/tasks", params)
        if data:
            tasks.extend(data)

        if not next_page or not next_page.get("offset"):
            break

        params["offset"] = next_page["offset"]
        print(f"  Fetching more tasks... ({len(tasks)} so far)")

    return tasks

def get_sections(project_gid):
    """Get sections (columns) from a project."""
    data, _ = asana_request(f"projects/{project_gid}/sections")
    return data

def extract_campaign_info(task):
    """Extract campaign-relevant info from an Asana task."""

    # Get section (often used for status or month)
    section = None
    if task.get("memberships"):
        for m in task["memberships"]:
            if m.get("section"):
                section = m["section"].get("name")
                break

    # Get custom field values
    custom_fields = {}
    for cf in task.get("custom_fields", []):
        if cf.get("display_value"):
            custom_fields[cf["name"]] = cf["display_value"]

    # Get tags
    tags = [t["name"] for t in task.get("tags", [])]

    return {
        "asana_gid": task["gid"],
        "name": task["name"],
        "notes": task.get("notes", ""),
        "start_date": task.get("start_on"),
        "due_date": task.get("due_on"),
        "completed": task.get("completed", False),
        "section": section,
        "tags": tags,
        "custom_fields": custom_fields,
        "assignee": task.get("assignee", {}).get("name") if task.get("assignee") else None,
        "created_at": task.get("created_at"),
        "modified_at": task.get("modified_at"),
    }

def infer_channel(task_name, tags):
    """Infer channel from task name or tags."""
    name_lower = task_name.lower()
    tags_lower = [t.lower() for t in tags]

    if "sms" in name_lower or "sms" in tags_lower:
        return "sms"
    if "push" in name_lower or "push" in tags_lower:
        return "push"
    if "email" in name_lower or "email" in tags_lower:
        return "email"

    return "email"  # default

def group_by_campaign(tasks):
    """
    Attempt to group tasks into campaigns.

    This uses heuristics - adjust based on how your Asana is organized.
    Common patterns:
    - Tasks grouped by section (each section = a campaign)
    - Parent tasks with subtasks
    - Tasks with similar prefixes/dates
    """
    campaigns = {}

    for task in tasks:
        # Use section as campaign grouping if available
        campaign_key = task.get("section") or "Ungrouped"

        if campaign_key not in campaigns:
            campaigns[campaign_key] = {
                "name": campaign_key,
                "tasks": []
            }

        campaigns[campaign_key]["tasks"].append(task)

    return campaigns

def transform_to_calendar(tasks):
    """Transform Asana tasks to a calendar-friendly format."""
    calendar = []

    for task in tasks:
        entry = {
            "name": task["name"],
            "channel": infer_channel(task["name"], task["tags"]),
            "date": task.get("due_date") or task.get("start_date"),
            "status": "completed" if task["completed"] else "scheduled",
            "asana_gid": task["asana_gid"],
            "notes": task["notes"][:200] if task["notes"] else None,
            "tags": task["tags"],
        }

        # Add custom fields
        for key, value in task.get("custom_fields", {}).items():
            entry[f"cf_{key.lower().replace(' ', '_')}"] = value

        calendar.append(entry)

    # Sort by date
    calendar.sort(key=lambda x: x.get("date") or "9999-99-99")

    return calendar

def write_output(data, output_path, dry_run=False):
    """Write data to YAML file."""
    if dry_run:
        print(f"Would write to: {output_path}")
        print(yaml.dump(data, default_flow_style=False, sort_keys=False)[:1000])
        print("...")
        return

    with open(output_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Wrote: {output_path}")

def list_projects_cmd(workspace_name=None):
    """List available projects."""
    workspaces = get_workspaces()
    if not workspaces:
        print("No workspaces found")
        return

    for ws in workspaces:
        if workspace_name and workspace_name.lower() not in ws["name"].lower():
            continue

        print(f"\nWorkspace: {ws['name']}")
        print("-" * 40)

        projects = get_projects(ws["gid"])
        if projects:
            for p in projects:
                print(f"  - {p['name']}")
        else:
            print("  (no projects)")

BRAND_ALIASES = {
    "id": "Interior Define",
    "interior define": "Interior Define",
    "ti": "The Inside",
    "the inside": "The Inside",
    "cz": "The Citizenry",
    "the citizenry": "The Citizenry",
    "havenly": "Havenly",
    "hav": "Havenly",
    "burrow": "Burrow",
    "bur": "Burrow",
    "stf": "St. Frank",
    "st. frank": "St. Frank",
    "st frank": "St. Frank",
}

def normalize_brand(brand):
    """Normalize brand name to canonical form."""
    if not brand:
        return None
    return BRAND_ALIASES.get(brand.lower(), brand)

def main():
    parser = argparse.ArgumentParser(description="Import campaign data from Asana")
    parser.add_argument("--project", type=str, help="Project name to import")
    parser.add_argument("--workspace", type=str, help="Workspace name")
    parser.add_argument("--brand", type=str, help="Filter by brand (e.g., 'ID', 'Interior Define')")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--list-projects", action="store_true", help="List projects and exit")
    parser.add_argument("--output", type=str, default="imports/asana_calendar.yaml", help="Output filename")
    args = parser.parse_args()

    if args.list_projects:
        list_projects_cmd(args.workspace)
        return

    if not args.project:
        print("Error: --project is required")
        print("Use --list-projects to see available projects")
        sys.exit(1)

    # Find workspace
    workspaces = get_workspaces()
    if not workspaces:
        print("No workspaces found")
        sys.exit(1)

    workspace = workspaces[0]  # Default to first
    if args.workspace:
        for ws in workspaces:
            if args.workspace.lower() in ws["name"].lower():
                workspace = ws
                break

    print(f"Using workspace: {workspace['name']}")

    # Find project
    project = find_project(workspace["gid"], args.project)
    if not project:
        print(f"Project '{args.project}' not found")
        print("Use --list-projects to see available projects")
        sys.exit(1)

    print(f"Found project: {project['name']}")
    print()

    # Get tasks
    print("Fetching tasks...")
    tasks = get_tasks(project["gid"])
    print(f"Found {len(tasks)} tasks")

    # Extract campaign info
    processed_tasks = [extract_campaign_info(t) for t in tasks]

    # Filter by brand if specified
    if args.brand:
        target_brand = normalize_brand(args.brand)
        processed_tasks = [
            t for t in processed_tasks
            if normalize_brand(t.get("custom_fields", {}).get("Brand")) == target_brand
        ]
        print(f"Filtered to {len(processed_tasks)} {target_brand} tasks")

    # Transform to calendar format
    calendar = transform_to_calendar(processed_tasks)

    # Also group by campaign
    campaigns = group_by_campaign(processed_tasks)

    # Prepare output
    output_data = {
        "source": "asana",
        "project": project["name"],
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "calendar": calendar,
        "by_campaign": {
            name: {
                "name": name,
                "task_count": len(data["tasks"]),
                "date_range": {
                    "start": min((t.get("start_date") or t.get("due_date") or "9999") for t in data["tasks"]),
                    "end": max((t.get("due_date") or t.get("start_date") or "0000") for t in data["tasks"]),
                },
                "tasks": [t["name"] for t in data["tasks"]]
            }
            for name, data in campaigns.items()
        }
    }

    # Write output
    script_dir = Path(__file__).parent
    output_path = script_dir.parent / args.output

    write_output(output_data, output_path, args.dry_run)

    print()
    print(f"Done! Imported {len(calendar)} tasks from '{project['name']}'")
    print(f"Found {len(campaigns)} campaign groups")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Explore an Asana project structure and return a complete summary.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"

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

def get_project(project_gid):
    """Get project details."""
    data, _ = asana_request(f"projects/{project_gid}", {
        "opt_fields": "name,notes,created_at,modified_at,public,archived,color,default_view"
    })
    return data

def get_sections(project_gid):
    """Get all sections in a project."""
    data, _ = asana_request(f"projects/{project_gid}/sections", {
        "opt_fields": "name,gid"
    })
    return data or []

def get_tasks_in_section(section_gid):
    """Get all tasks in a specific section."""
    tasks = []
    params = {
        "opt_fields": "name,due_on,completed,completed_at,created_at,assignee.name,custom_fields.name,custom_fields.display_value",
        "limit": 100
    }
    
    while True:
        data, next_page = asana_request(f"sections/{section_gid}/tasks", params)
        if data:
            tasks.extend(data)
        
        if not next_page or not next_page.get("offset"):
            break
        
        params["offset"] = next_page["offset"]
    
    return tasks

def get_task_details(task_gid):
    """Get detailed information about a task."""
    data, _ = asana_request(f"tasks/{task_gid}", {
        "opt_fields": "name,notes,due_on,start_on,completed,completed_at,created_at,modified_at,assignee.name,assignee.email,tags.name,custom_fields.name,custom_fields.display_value,custom_fields.enum_value.name"
    })
    return data

def main():
    project_gid = "1213017796586525"
    workspace_gid = "5257710284167"
    
    print(f"Exploring Asana project: {project_gid}")
    print(f"Workspace: {workspace_gid}")
    print("=" * 80)
    print()
    
    # 1. Get project details
    print("1. Fetching project details...")
    project = get_project(project_gid)
    if not project:
        print(f"Error: Could not fetch project {project_gid}")
        sys.exit(1)
    
    print(f"   Project Name: {project.get('name')}")
    print(f"   Description: {project.get('notes', 'No description')[:200]}")
    print()
    
    # 2. Get sections
    print("2. Fetching sections...")
    sections = get_sections(project_gid)
    print(f"   Found {len(sections)} sections")
    print()
    
    # 3. Get tasks for each section
    print("3. Fetching tasks for each section...")
    section_data = []
    
    for section in sections:
        section_gid = section.get("gid")
        section_name = section.get("name")
        print(f"   Section: {section_name} ({section_gid})")
        
        tasks = get_tasks_in_section(section_gid)
        print(f"      Found {len(tasks)} tasks")
        
        section_data.append({
            "section": section,
            "tasks": tasks
        })
    
    print()
    
    # 4. Get detailed task info for populated sections
    print("4. Getting detailed task information for populated sections...")
    detailed_sections = []
    
    for section_info in section_data:
        section = section_info["section"]
        tasks = section_info["tasks"]
        
        if len(tasks) > 0:
            print(f"   Getting details for {len(tasks)} tasks in '{section['name']}'...")
            detailed_tasks = []
            for task in tasks[:20]:  # Limit to first 20 for performance
                task_details = get_task_details(task["gid"])
                if task_details:
                    detailed_tasks.append(task_details)
            
            detailed_sections.append({
                "section": section,
                "tasks": detailed_tasks,
                "total_tasks": len(tasks)
            })
    
    # Output summary
    print()
    print("=" * 80)
    print("PROJECT SUMMARY")
    print("=" * 80)
    print()
    print(f"Project Name: {project.get('name')}")
    print(f"Project GID: {project_gid}")
    print(f"Description: {project.get('notes', 'No description')}")
    print(f"Created: {project.get('created_at')}")
    print(f"Modified: {project.get('modified_at')}")
    print(f"Public: {project.get('public', False)}")
    print(f"Archived: {project.get('archived', False)}")
    print()
    
    print("=" * 80)
    print("SECTIONS AND TASKS")
    print("=" * 80)
    print()
    
    for section_info in section_data:
        section = section_info["section"]
        tasks = section_info["tasks"]
        
        print(f"Section: {section['name']}")
        print(f"  GID: {section['gid']}")
        print(f"  Total Tasks: {len(tasks)}")
        print()
        
        if tasks:
            print("  Tasks:")
            for task in tasks[:50]:  # Show first 50
                name = task.get("name", "Unnamed")
                completed = "✓" if task.get("completed") else "○"
                due_on = task.get("due_on", "No due date")
                assignee_data = task.get("assignee")
                assignee = assignee_data.get("name", "Unassigned") if assignee_data else "Unassigned"
                print(f"    {completed} {name}")
                print(f"      Due: {due_on}, Assignee: {assignee}")
            if len(tasks) > 50:
                print(f"    ... and {len(tasks) - 50} more tasks")
        print()
    
    # Detailed view for populated sections
    if detailed_sections:
        print("=" * 80)
        print("DETAILED TASK INFORMATION (Sample)")
        print("=" * 80)
        print()
        
        for section_info in detailed_sections:
            section = section_info["section"]
            detailed_tasks = section_info["tasks"]
            total = section_info["total_tasks"]
            
            print(f"Section: {section['name']} ({len(detailed_tasks)} of {total} tasks shown)")
            print()
            
            for task in detailed_tasks:
                print(f"  Task: {task.get('name')}")
                print(f"    GID: {task.get('gid')}")
                print(f"    Completed: {task.get('completed', False)}")
                if task.get('completed_at'):
                    print(f"    Completed At: {task.get('completed_at')}")
                print(f"    Due On: {task.get('due_on', 'No due date')}")
                print(f"    Start On: {task.get('start_on', 'No start date')}")
                assignee_data = task.get('assignee')
                assignee_name = assignee_data.get('name', 'Unassigned') if assignee_data else 'Unassigned'
                print(f"    Assignee: {assignee_name}")
                
                tags = task.get('tags', [])
                if tags:
                    tag_names = [t.get('name') for t in tags if t.get('name')]
                    print(f"    Tags: {', '.join(tag_names)}")
                
                custom_fields = task.get('custom_fields', [])
                if custom_fields:
                    print(f"    Custom Fields:")
                    for cf in custom_fields:
                        name = cf.get('name')
                        value = cf.get('display_value') or cf.get('enum_value', {}).get('name')
                        if name and value:
                            print(f"      - {name}: {value}")
                
                notes = task.get('notes', '')
                if notes:
                    preview = notes[:100].replace('\n', ' ')
                    print(f"    Notes: {preview}...")
                
                print()
    
    # Save full JSON output
    output = {
        "project": project,
        "sections": [
            {
                "section": section_info["section"],
                "tasks": section_info["tasks"],
                "task_count": len(section_info["tasks"])
            }
            for section_info in section_data
        ],
        "detailed_tasks": {
            section_info["section"]["name"]: section_info["tasks"]
            for section_info in detailed_sections
        }
    }
    
    output_file = Path(__file__).parent.parent / "exports" / f"asana_project_{project_gid}.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"Full JSON output saved to: {output_file}")

if __name__ == "__main__":
    main()

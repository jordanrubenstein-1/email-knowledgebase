#!/usr/bin/env python3
"""
Apply approved AI feedback changes from the "AI Build Feedback" Asana project.

Reads tasks in the "To Implement" section, applies the suggested changes, then
moves them to "Implemented" and posts a comment with what was changed.

What can be auto-applied:
  - copy_guideline  → appends entry to data/ai_build_guidelines.yaml
  - config_change   → prints the suggested change for you to apply manually
                      (config edits are too high-risk to auto-apply)
  - prompt_change   → prints the suggested diff for manual review
  - no_action       → moves to Implemented with a note

Usage:
    # Preview what would be applied
    uv run python scripts/apply_ai_feedback.py --dry-run

    # Apply all approved (To Implement) items
    uv run python scripts/apply_ai_feedback.py
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional

import yaml
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
FEEDBACK_PROJECT_ENV = "ASANA_FEEDBACK_PROJECT_GID"

SECTION_TO_IMPLEMENT = "To Implement"
SECTION_IMPLEMENTED = "Implemented"

GUIDELINES_PATH = PROJECT_ROOT / "data" / "ai_build_guidelines.yaml"
AI_FEEDBACK_LOG = PROJECT_ROOT / "data" / "ai_feedback_log.yaml"


# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def _asana_headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: ASANA_ACCESS_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _asana_request(method: str, endpoint: str, json_data=None, params=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=_asana_headers(),
                            json=json_data, params=params, timeout=30)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        time.sleep(wait)
        resp = requests.request(method, url, headers=_asana_headers(),
                                json=json_data, params=params, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"Asana {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json().get("data")


def get_section_gid(project_gid: str, section_name: str) -> Optional[str]:
    sections = _asana_request("GET", f"projects/{project_gid}/sections",
                              params={"opt_fields": "gid,name"})
    if not sections:
        return None
    for s in sections:
        if s.get("name") == section_name:
            return s["gid"]
    return None


def get_tasks_in_section(section_gid: str) -> list:
    resp = requests.get(
        f"{ASANA_BASE_URL}/sections/{section_gid}/tasks",
        headers=_asana_headers(),
        params={"opt_fields": "gid,name,notes", "limit": 100},
        timeout=30,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("data", [])


def move_task_to_section(task_gid: str, section_gid: str) -> bool:
    result = _asana_request(
        "POST",
        f"sections/{section_gid}/addTask",
        json_data={"data": {"task": task_gid}},
    )
    return result is not None


def post_task_comment(task_gid: str, text: str) -> None:
    _asana_request(
        "POST",
        f"tasks/{task_gid}/stories",
        json_data={"data": {"text": text}},
    )


# ---------------------------------------------------------------------------
# Parse evaluation from task notes
# ---------------------------------------------------------------------------

def parse_notes(notes: str) -> dict:
    """
    Extract structured fields from the Asana task notes written by process_ai_feedback.py.
    Returns a dict with keys: raw_comment, insight, suggested_action, category, confidence, log_id
    """
    result = {}
    current_key = None
    lines = notes.split("\n")
    buffer = []

    MARKERS = {
        "── What the producer changed ──": "raw_comment",
        "── AI Insight ──": "insight",
        "── Suggested Action ──": "suggested_action",
    }

    for line in lines:
        if line in MARKERS:
            if current_key and buffer:
                result[current_key] = "\n".join(buffer).strip()
                buffer = []
            current_key = MARKERS[line]
        elif line.startswith("Confidence:") and current_key:
            if buffer:
                result[current_key] = "\n".join(buffer).strip()
                buffer = []
            current_key = None
            result["confidence"] = line.replace("Confidence:", "").strip().lower()
        elif line.startswith("Category:") and current_key is None:
            result["category"] = line.replace("Category:", "").strip()
        elif line.startswith("Log ID:") or "Log ID:" in line:
            parts = line.split("Log ID:")
            if len(parts) > 1:
                result["log_id"] = parts[1].strip()
        elif current_key:
            buffer.append(line)

    if current_key and buffer:
        result[current_key] = "\n".join(buffer).strip()

    return result


# ---------------------------------------------------------------------------
# Apply logic per category
# ---------------------------------------------------------------------------

def apply_copy_guideline(task_gid: str, task_name: str, parsed: dict, dry_run: bool) -> str:
    """Append guideline to data/ai_build_guidelines.yaml."""
    # Extract brand/channel from task name like "[BUR · SMS] ..."
    brand, channel = None, None
    if task_name.startswith("[") and "·" in task_name:
        inner = task_name[1:task_name.index("]")]
        parts = inner.split("·")
        if len(parts) == 2:
            brand = parts[0].strip()
            channel = parts[1].strip().lower()

    guideline_text = parsed.get("suggested_action") or parsed.get("insight") or "See task notes"
    log_id = parsed.get("log_id", "unknown")

    entry = {
        "id": f"fb-{log_id}",
        "brand": brand,
        "channel": channel,
        "guideline": guideline_text,
        "source_task_gid": task_gid,
        "added": __import__("datetime").date.today().isoformat(),
    }

    if dry_run:
        return f"[DRY RUN] Would append to {GUIDELINES_PATH.name}:\n{yaml.dump(entry, default_flow_style=False)}"

    # Load/create guidelines file
    if GUIDELINES_PATH.exists():
        with open(GUIDELINES_PATH) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {
            "# AI-learned build preferences from producer feedback": None,
            "# Reviewed and approved by human before adding": None,
        }

    data.setdefault("guidelines", [])
    data["guidelines"].append(entry)

    with open(GUIDELINES_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return f"Appended guideline to {GUIDELINES_PATH.name}"


def apply_config_change(parsed: dict, dry_run: bool) -> str:
    """Config changes require manual review — print the suggestion."""
    suggestion = parsed.get("suggested_action", "(no suggestion)")
    return (
        f"CONFIG CHANGE REQUIRED (manual):\n{suggestion}\n\n"
        f"File to update: data/brand_config.yaml"
    )


def apply_prompt_change(parsed: dict, dry_run: bool) -> str:
    """Prompt changes require manual review — print the suggestion."""
    suggestion = parsed.get("suggested_action", "(no suggestion)")
    return (
        f"PROMPT CHANGE REQUIRED (manual):\n{suggestion}\n\n"
        f"File to update: scripts/create_calendar_tasks.py (lines 453-565)"
    )


def apply_entry(task_gid: str, task_name: str, notes: str, dry_run: bool) -> str:
    """Dispatch to the appropriate apply function based on category."""
    parsed = parse_notes(notes)
    category = parsed.get("category", "no_action")

    if category == "copy_guideline":
        return apply_copy_guideline(task_gid, task_name, parsed, dry_run)
    elif category == "config_change":
        return apply_config_change(parsed, dry_run)
    elif category == "prompt_change":
        return apply_prompt_change(parsed, dry_run)
    else:
        return "No action needed — marking as implemented."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing or moving tasks")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("[DRY RUN] No changes will be written")

    feedback_project_gid = os.environ.get(FEEDBACK_PROJECT_ENV, "").strip()
    if not feedback_project_gid:
        print(f"ERROR: {FEEDBACK_PROJECT_ENV} not set in .env", file=sys.stderr)
        print("Run: uv run python scripts/process_ai_feedback.py --setup", file=sys.stderr)
        sys.exit(1)

    # Get sections
    implement_gid = get_section_gid(feedback_project_gid, SECTION_TO_IMPLEMENT)
    implemented_gid = get_section_gid(feedback_project_gid, SECTION_IMPLEMENTED)

    if not implement_gid:
        print(f"ERROR: Section '{SECTION_TO_IMPLEMENT}' not found in feedback project", file=sys.stderr)
        sys.exit(1)

    # Get tasks in "To Implement"
    tasks = get_tasks_in_section(implement_gid)
    if not tasks:
        logger.info(f"No tasks in '{SECTION_TO_IMPLEMENT}' — nothing to apply.")
        return

    logger.info(f"Found {len(tasks)} task(s) in '{SECTION_TO_IMPLEMENT}'")

    applied_count = 0
    for task in tasks:
        task_gid = task["gid"]
        task_name = task.get("name", task_gid)
        notes = task.get("notes", "")

        logger.info(f"\n→ {task_name}")
        result_msg = apply_entry(task_gid, task_name, notes, dry_run=args.dry_run)
        logger.info(f"  {result_msg}")

        if not args.dry_run:
            # Post comment with what was done
            comment = f"Applied:\n{result_msg}"
            post_task_comment(task_gid, comment)

            # Move to Implemented
            if implemented_gid:
                move_task_to_section(task_gid, implemented_gid)
                logger.info(f"  → Moved to '{SECTION_IMPLEMENTED}'")

            applied_count += 1

    if not args.dry_run:
        logger.info(f"\nDone. Applied {applied_count} change(s).")
    else:
        logger.info(f"\n[DRY RUN] Would apply {len(tasks)} change(s).")


if __name__ == "__main__":
    main()

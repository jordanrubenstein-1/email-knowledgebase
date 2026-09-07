#!/usr/bin/env python3
"""
Process AI feedback comments from Asana campaign tasks.

Two-phase operation:
1. Backfill scan  — polls Asana for recent "AI feedback:" stories not yet in
                    data/ai_feedback_log.yaml (ngrok-independent catch-up).
2. Evaluate       — Claude evaluates each unprocessed entry, then creates a
                    task in the "AI Build Feedback" Asana project for you to
                    triage (Implement / Ignore / Done).

The feedback project must exist in Asana before running. Run with --setup once
to create it (requires ASANA_ACCESS_TOKEN and a writable workspace).

Usage:
    # Full run (backfill + evaluate + post to Asana)
    uv run python scripts/process_ai_feedback.py

    # Preview only — no writes
    uv run python scripts/process_ai_feedback.py --dry-run

    # Skip the Asana backfill scan (only process what's already in the log)
    uv run python scripts/process_ai_feedback.py --no-backfill

    # Override lookback window for first run (default: 14 days)
    # Subsequent runs automatically resume from the last scan timestamp
    uv run python scripts/process_ai_feedback.py --days 30

    # Create the "AI Build Feedback" Asana project (run once)
    uv run python scripts/process_ai_feedback.py --setup
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Asana constants (same as build_sms_campaign.py)
# ---------------------------------------------------------------------------
ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"   # Master CRM (Email & SMS)
ASANA_WORKSPACE_GID = "5257710284167"   # havenly.com

FIELD_CHANNEL = "1207562370794988"
CHANNEL_OPTIONS = {
    "email": "1207562370794989",
    "sms": "1207562370794990",
    "push": "1207562370794991",
}
CHANNEL_GID_TO_NAME = {v: k for k, v in CHANNEL_OPTIONS.items()}
FIELD_BRAND = "1207522425689880"

# Brand GID → code mapping (must match BRAND_OPTIONS in build_sms_campaign.py)
BRAND_GID_TO_CODE = {
    "1207522425689881": "HAV",
    "1207553690167887": "CZ",
    "1207522425689882": "ID",
    "1208572919795447": "BUR",
    "1207522425689883": "TI",
    "1207881071843537": "STF",
    "1208130746998739": "TRADE",
}

# Env var for the feedback project GID
FEEDBACK_PROJECT_ENV = "ASANA_FEEDBACK_PROJECT_GID"

# Section names in the AI Build Feedback project
SECTION_NEW = "New"
SECTION_TO_IMPLEMENT = "To Implement"
SECTION_IMPLEMENTED = "Implemented"
SECTION_IGNORED = "Ignored"

AI_FEEDBACK_LOG = PROJECT_ROOT / "data" / "ai_feedback_log.yaml"
BRAND_CONFIG_PATH = PROJECT_ROOT / "data" / "brand_config.yaml"
GUIDELINES_PATH = PROJECT_ROOT / "data" / "ai_build_guidelines.yaml"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def _asana_headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: ASANA_ACCESS_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _asana_request(method: str, endpoint: str, json_data=None, params=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(
        method, url, headers=_asana_headers(), json=json_data, params=params, timeout=30
    )
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        logger.warning(f"Rate limited — waiting {wait}s")
        time.sleep(wait)
        resp = requests.request(
            method, url, headers=_asana_headers(), json=json_data, params=params, timeout=30
        )
    if resp.status_code not in (200, 201):
        logger.error(f"Asana {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json().get("data")


def _asana_paginate(endpoint: str, params: dict) -> list:
    """Fetch all pages from an Asana list endpoint."""
    results = []
    offset = None
    while True:
        p = dict(params)
        if offset:
            p["offset"] = offset
        resp_url = f"{ASANA_BASE_URL}/{endpoint}"
        resp = requests.get(resp_url, headers=_asana_headers(), params=p, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 30))
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            logger.error(f"Asana {resp.status_code}: {resp.text[:200]}")
            break
        body = resp.json()
        results.extend(body.get("data", []))
        next_page = body.get("next_page")
        if next_page and next_page.get("offset"):
            offset = next_page["offset"]
        else:
            break
    return results


def fetch_project_tasks_modified_since(modified_since: datetime) -> list:
    """Fetch all tasks in Master CRM project modified after the given datetime."""
    since_str = modified_since.strftime("%Y-%m-%dT%H:%M:%SZ")
    opt_fields = ",".join([
        "gid", "name", "modified_at",
        "custom_fields", "custom_fields.gid",
        "custom_fields.enum_value", "custom_fields.enum_value.gid",
        "custom_fields.enum_value.name",
    ])
    return _asana_paginate(
        f"projects/{ASANA_PROJECT_GID}/tasks",
        params={
            "modified_since": since_str,
            "opt_fields": opt_fields,
            "limit": 100,
        },
    )


def fetch_task_stories(task_gid: str) -> list:
    """Fetch all stories for a task, returning only comments."""
    stories = _asana_paginate(
        f"tasks/{task_gid}/stories",
        params={
            "opt_fields": "gid,type,text,created_by.name,created_at",
            "limit": 100,
        },
    )
    return [s for s in stories if s.get("type") == "comment"]


def get_section_gid(project_gid: str, section_name: str) -> Optional[str]:
    """Look up a section GID by name within a project."""
    sections = _asana_request("GET", f"projects/{project_gid}/sections",
                              params={"opt_fields": "gid,name"})
    if not sections:
        return None
    for s in sections:
        if s.get("name") == section_name:
            return s["gid"]
    return None


def create_asana_task(project_gid: str, name: str, notes: str, section_gid: Optional[str] = None) -> Optional[str]:
    """Create a task in the feedback project. Returns task GID."""
    payload = {
        "data": {
            "name": name,
            "notes": notes,
            "projects": [project_gid],
        }
    }
    task = _asana_request("POST", "tasks", json_data=payload)
    if not task:
        return None
    task_gid = task["gid"]
    # Move to section
    if section_gid:
        _asana_request(
            "POST",
            f"sections/{section_gid}/addTask",
            json_data={"data": {"task": task_gid}},
        )
    return task_gid


# ---------------------------------------------------------------------------
# Feedback log helpers
# ---------------------------------------------------------------------------

def load_log() -> dict:
    if not AI_FEEDBACK_LOG.exists():
        return {"entries": []}
    with open(AI_FEEDBACK_LOG) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("entries", [])
    return data


def save_log(data: dict) -> None:
    with open(AI_FEEDBACK_LOG, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Phase 1: Backfill scan
# ---------------------------------------------------------------------------

def _get_channel_name(task: dict) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == FIELD_CHANNEL and cf.get("enum_value"):
            gid = cf["enum_value"].get("gid")
            return CHANNEL_GID_TO_NAME.get(gid)
    return None


def _get_brand_code(task: dict) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == FIELD_BRAND and cf.get("enum_value"):
            gid = cf["enum_value"].get("gid")
            return BRAND_GID_TO_CODE.get(gid)
    return None


def backfill_scan(days: int, dry_run: bool) -> list:
    """
    Poll Asana for recent stories containing "AI feedback:" not yet in the log.

    Uses last_backfill_at from the log to narrow the window on repeat runs.
    Only falls back to `days` on the very first run (no prior scan timestamp).
    Returns list of new entries added.
    """
    log_data = load_log()
    last_scan = log_data.get("last_backfill_at")
    now = datetime.now(timezone.utc)

    if last_scan:
        # Use last scan time + small buffer so we don't miss anything at boundaries
        since = datetime.fromisoformat(last_scan) - timedelta(hours=1)
        elapsed = (now - since).days
        logger.info(f"Backfill scan: resuming from last scan ({last_scan[:10]}, {elapsed}d ago)...")
    else:
        since = now - timedelta(days=days)
        logger.info(f"Backfill scan: first run — fetching tasks modified since {since.strftime('%Y-%m-%d')} ({days} days)...")

    tasks = fetch_project_tasks_modified_since(since)
    logger.info(f"  Found {len(tasks)} modified task(s)")

    # Only scan tasks with Channel = SMS, Push, or Email
    auto_build_channels = set(CHANNEL_OPTIONS.values())
    relevant_tasks = []
    for t in tasks:
        channel_gid = next(
            (cf.get("enum_value", {}).get("gid")
             for cf in t.get("custom_fields", [])
             if cf.get("gid") == FIELD_CHANNEL and cf.get("enum_value")),
            None,
        )
        if channel_gid in auto_build_channels:
            relevant_tasks.append(t)

    logger.info(f"  {len(relevant_tasks)} task(s) with auto-build channels")

    # Load existing story GIDs to dedup
    log_data = load_log()
    existing_story_gids = {e.get("story_gid") for e in log_data["entries"]}

    new_entries = []
    for task in relevant_tasks:
        task_gid = task["gid"]
        task_name = task.get("name", task_gid)
        brand_code = _get_brand_code(task)
        channel_name = _get_channel_name(task)

        stories = fetch_task_stories(task_gid)
        for story in stories:
            story_gid = story.get("gid")
            if story_gid in existing_story_gids:
                continue
            text = (story.get("text") or "").strip()
            if "ai feedback" not in text.lower():
                continue

            commenter = story.get("created_by", {}).get("name", "Unknown")
            captured_at = story.get("created_at", datetime.now(timezone.utc).isoformat())

            entry = {
                "id": str(uuid.uuid4())[:8],
                "story_gid": story_gid,
                "source": "backfill",
                "captured_at": captured_at,
                "task_gid": task_gid,
                "task_name": task_name,
                "brand": brand_code,
                "channel": channel_name,
                "commenter": commenter,
                "raw_comment": text,
                "status": "unprocessed",
                "asana_feedback_task_gid": None,
            }

            existing_story_gids.add(story_gid)
            new_entries.append(entry)
            logger.info(f"  [backfill] {commenter} on '{task_name}': {text[:80]}")

    if not dry_run:
        # Reload fresh before writing to handle any concurrent webhook writes
        log_data = load_log()
        existing_gids_final = {e.get("story_gid") for e in log_data["entries"]}
        added = 0
        for entry in new_entries:
            if entry["story_gid"] not in existing_gids_final:
                log_data["entries"].append(entry)
                existing_gids_final.add(entry["story_gid"])
                added += 1
        log_data["last_backfill_at"] = now.isoformat()
        save_log(log_data)
        if added:
            logger.info(f"Backfill: added {added} new entry/entries to log")
        else:
            logger.info("Backfill: no new AI feedback found")
    elif new_entries:
        logger.info(f"[DRY RUN] Would add {len(new_entries)} new entry/entries")
    else:
        logger.info("Backfill: no new AI feedback found")

    return new_entries


# ---------------------------------------------------------------------------
# Phase 2: Claude evaluation
# ---------------------------------------------------------------------------

def _load_brand_config_snippet(brand: Optional[str], channel: Optional[str]) -> str:
    """Load the relevant section of brand_config.yaml for context."""
    if not BRAND_CONFIG_PATH.exists():
        return ""
    with open(BRAND_CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    snippets = []
    if channel == "sms" and brand:
        sms = config.get("sms_config", {}).get(brand)
        if sms:
            snippets.append(f"SMS config for {brand}:\n" + yaml.dump(sms, default_flow_style=False))
    elif channel == "push" and brand:
        push = config.get("push_config", {}).get(brand)
        if push:
            snippets.append(f"Push config for {brand}:\n" + yaml.dump(push, default_flow_style=False))
    elif channel == "email" and brand:
        pt = config.get("email_pt_config", {}).get(brand)
        if pt:
            snippets.append(f"Plain-text email config for {brand}:\n" + yaml.dump(pt, default_flow_style=False))

    return "\n".join(snippets) if snippets else "(config not found for this brand/channel)"


def _load_existing_guidelines() -> str:
    """Load any existing AI build guidelines for context."""
    if not GUIDELINES_PATH.exists():
        return "(none yet)"
    with open(GUIDELINES_PATH) as f:
        data = yaml.safe_load(f) or {}
    guidelines = data.get("guidelines", [])
    if not guidelines:
        return "(none yet)"
    lines = []
    for g in guidelines:
        lines.append(f"- [{g.get('brand', '?')} {g.get('channel', '?')}] {g.get('guideline', '')}")
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are an AI campaign build assistant evaluating producer corrections to AI-built \
marketing campaigns (SMS, push, plain-text email). Your job is to analyze what the \
producer changed and suggest a specific, actionable improvement to the AI build \
configuration so this correction won't be needed in future.

Respond ONLY with valid JSON matching this schema exactly (no markdown, no preamble):
{
  "category": "<config_change|copy_guideline|prompt_change|no_action>",
  "insight": "<1-2 sentence interpretation of what this implies about the build rule>",
  "suggested_action": "<specific change to make, including file/field/value>",
  "confidence": "<high|medium|low>",
  "flag_for_human": <true|false>
}

Categories:
- config_change: a field in brand_config.yaml should be updated
- copy_guideline: a guideline about copy length, tone, or content should be added
- prompt_change: the Claude prompt used to generate subject lines or briefs needs updating
- no_action: feedback is already handled, is too vague, or is a one-off exception
"""


def evaluate_with_claude(entry: dict) -> Optional[dict]:
    """Call Claude to evaluate a single feedback entry. Returns parsed JSON dict."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed — run: uv add anthropic")
        return None

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    config_snippet = _load_brand_config_snippet(entry.get("brand"), entry.get("channel"))
    guidelines_snippet = _load_existing_guidelines()

    user_msg = f"""\
Campaign task: {entry.get("task_name", "unknown")}
Brand: {entry.get("brand", "unknown")} | Channel: {entry.get("channel", "unknown")}
Producer's feedback comment:
  {entry["raw_comment"]}

Current build config for this brand/channel:
{config_snippet}

Existing AI build guidelines (already incorporated):
{guidelines_snippet}

Evaluate this feedback and return the JSON response."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Claude returned non-JSON: {e}\nRaw: {raw[:200]}")
        return None
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return None


def format_asana_task_notes(entry: dict, evaluation: dict) -> str:
    """Format the Asana feedback task body."""
    lines = [
        "── What the producer changed ──",
        entry["raw_comment"],
        "",
        "── AI Insight ──",
        evaluation.get("insight", ""),
        "",
        "── Suggested Action ──",
        evaluation.get("suggested_action", ""),
        "",
        f"Confidence: {evaluation.get('confidence', '?').upper()}",
        f"Category: {evaluation.get('category', '?')}",
        "",
        "── Original Campaign Task ──",
        f"https://app.asana.com/0/{ASANA_PROJECT_GID}/{entry['task_gid']}",
        "",
        f"Captured: {entry.get('captured_at', '')}",
        f"Commenter: {entry.get('commenter', '?')}",
        f"Source: {entry.get('source', '?')} | Log ID: {entry.get('id', '?')}",
    ]
    return "\n".join(lines)


def format_task_title(entry: dict, evaluation: dict) -> str:
    """Format a concise, scannable Asana task title."""
    brand = entry.get("brand") or "?"
    channel = (entry.get("channel") or "?").upper()
    insight = evaluation.get("insight", entry["raw_comment"][12:].strip())
    # Truncate insight for title
    max_insight = 80
    if len(insight) > max_insight:
        insight = insight[:max_insight].rsplit(" ", 1)[0] + "…"
    return f"[{brand} · {channel}] {insight}"


# ---------------------------------------------------------------------------
# Phase 2: Post to Asana
# ---------------------------------------------------------------------------

def process_entries(dry_run: bool) -> None:
    """Evaluate unprocessed entries and create tasks in AI Build Feedback project."""
    feedback_project_gid = os.environ.get(FEEDBACK_PROJECT_ENV, "").strip()
    if not feedback_project_gid:
        logger.warning(
            f"\n{FEEDBACK_PROJECT_ENV} not set in .env.\n"
            "Set it to the GID of your 'AI Build Feedback' Asana project.\n"
            "Run with --setup to create the project automatically.\n"
        )
        if not dry_run:
            logger.error("Cannot post to Asana without project GID. Use --dry-run to preview.")
            return

    # Load sections if project exists
    section_new_gid = None
    if feedback_project_gid and not dry_run:
        section_new_gid = get_section_gid(feedback_project_gid, SECTION_NEW)
        if not section_new_gid:
            logger.warning(f"Section '{SECTION_NEW}' not found in project. Tasks will be unsectioned.")

    log_data = load_log()
    unprocessed = [e for e in log_data["entries"] if e.get("status") == "unprocessed"]

    if not unprocessed:
        logger.info("No unprocessed entries — nothing to evaluate.")
        return

    logger.info(f"Evaluating {len(unprocessed)} unprocessed entry/entries...")

    updated = 0
    for i, entry in enumerate(log_data["entries"]):
        if entry.get("status") != "unprocessed":
            continue

        logger.info(f"  [{i+1}] {entry.get('brand')} {entry.get('channel')} — {entry['raw_comment'][:60]}")

        evaluation = evaluate_with_claude(entry)
        if not evaluation:
            logger.warning(f"  Skipping entry {entry['id']} — Claude evaluation failed")
            continue

        logger.info(f"    → {evaluation.get('category')} ({evaluation.get('confidence')}) {evaluation.get('insight', '')[:60]}")

        if dry_run:
            print(f"\n{'='*60}")
            print(f"Task: {format_task_title(entry, evaluation)}")
            print(f"Notes:\n{format_asana_task_notes(entry, evaluation)}")
            print(f"{'='*60}\n")
            entry["status"] = "unprocessed"  # don't persist in dry run
            continue

        # Create Asana task
        title = format_task_title(entry, evaluation)
        notes = format_asana_task_notes(entry, evaluation)
        task_gid = create_asana_task(feedback_project_gid, title, notes, section_new_gid)

        if task_gid:
            entry["status"] = "posted_to_asana"
            entry["asana_feedback_task_gid"] = task_gid
            entry["evaluation"] = evaluation
            logger.info(f"    ✓ Created Asana task {task_gid}")
        else:
            logger.error(f"    ✗ Failed to create Asana task for entry {entry['id']}")

        updated += 1

    if not dry_run:
        save_log(log_data)
        logger.info(f"Done. {updated} entry/entries posted to Asana.")


# ---------------------------------------------------------------------------
# Setup: create the AI Build Feedback project
# ---------------------------------------------------------------------------

def cmd_setup(dry_run: bool) -> None:
    """Create the 'AI Build Feedback' Asana project with required sections."""
    project_name = "AI Build Feedback"

    if dry_run:
        print(f"[DRY RUN] Would create Asana project: '{project_name}'")
        print(f"  Sections: {SECTION_NEW} / {SECTION_TO_IMPLEMENT} / {SECTION_IMPLEMENTED} / {SECTION_IGNORED}")
        return

    # Create project
    payload = {
        "data": {
            "name": project_name,
            "workspace": ASANA_WORKSPACE_GID,
            "team": "1207353799661626",  # E-Comm
            "privacy_setting": "private",
            "notes": (
                "AI-evaluated feedback from producer corrections to auto-built campaigns.\n"
                "Triage entries in 'New' → move to 'To Implement' or 'Ignored'.\n"
                "Run scripts/apply_ai_feedback.py after marking 'To Implement'."
            ),
        }
    }
    project = _asana_request("POST", "projects", json_data=payload)
    if not project:
        logger.error("Failed to create project")
        return

    project_gid = project["gid"]
    print(f"\n✓ Created project '{project_name}' (GID: {project_gid})")

    # Create sections (Asana creates a default empty section; we'll add ours)
    for section_name in [SECTION_NEW, SECTION_TO_IMPLEMENT, SECTION_IMPLEMENTED, SECTION_IGNORED]:
        s = _asana_request(
            "POST",
            f"projects/{project_gid}/sections",
            json_data={"data": {"name": section_name}},
        )
        if s:
            print(f"  ✓ Section '{section_name}' created")
        else:
            print(f"  ✗ Failed to create section '{section_name}'")

    print(f"\nAdd this to your .env:")
    print(f"  {FEEDBACK_PROJECT_ENV}={project_gid}")
    print()
    print("Then re-run: uv run python scripts/process_ai_feedback.py")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing anything")
    parser.add_argument("--no-backfill", action="store_true",
                        help="Skip the Asana backfill scan")
    parser.add_argument("--days", type=int, default=14,
                        help="Backfill lookback window for first run in days (default: 14; subsequent runs auto-resume from last scan)")
    parser.add_argument("--setup", action="store_true",
                        help="Create the AI Build Feedback Asana project (run once)")

    args = parser.parse_args()

    if args.setup:
        cmd_setup(dry_run=args.dry_run)
        return

    if args.dry_run:
        logger.info("[DRY RUN] No changes will be written")

    # Phase 1: Backfill
    if not args.no_backfill:
        backfill_scan(days=args.days, dry_run=args.dry_run)
    else:
        logger.info("Backfill scan skipped (--no-backfill)")

    # Phase 2: Evaluate + post to Asana
    process_entries(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

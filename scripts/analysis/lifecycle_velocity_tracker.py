#!/usr/bin/env python3
"""
Lifecycle Velocity Tracker

Measures email campaign build time from "Ready to Code" → build complete
(QA Proof Sent / Ready to Dispatch / Launched / task completed).

SLA threshold: 2 business days (18 business hours, 9 AM–6 PM ET, Mon–Fri).
Builder = whoever set "QA Proof Sent" (the actual build action).
If no QA Proof Sent exists, falls back to last task assignee before build-done.

Filters:
  - Email channel only
  - Excludes Type = "Triggered Journey" (flow/lifecycle tasks)
  - Excludes STO Test? = Yes (different scheduling requirements)

Usage:
    # Pull fresh data from Asana (saves to exports/asana_velocity_data.json)
    uv run python scripts/analysis/lifecycle_velocity_tracker.py --fetch

    # Patch due_on into cache (fast, ~30 seconds) — run before lead-time analysis
    uv run python scripts/analysis/lifecycle_velocity_tracker.py --patch-due-on

    # Generate report from cached data
    uv run python scripts/analysis/lifecycle_velocity_tracker.py

    # Last 90 days
    uv run python scripts/analysis/lifecycle_velocity_tracker.py --days 90
"""

import os
import sys
import json
import re
import argparse
import time
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from statistics import median, mean
from typing import Optional

import requests
from dotenv import load_dotenv

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    except ImportError:
        print("Error: zoneinfo not available. Use Python 3.9+")
        sys.exit(1)

# Load .env from project root
ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"

# Custom field GIDs (from existing scripts)
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_TYPE = "1207522425689987"
FIELD_STO_TEST = "1213318188891529"

# Enum option GIDs
CHANNEL_EMAIL = "1207562370794989"
TYPE_TRIGGERED_JOURNEY = "1209982215611000"
STO_TEST_YES = "1213318188891530"   # "Test" option (legacy name kept for import compat)
STO_TEST_YES_OPTION = "1213963710077692"  # "Yes" option
STO_TEST_GIDS = frozenset([STO_TEST_YES, STO_TEST_YES_OPTION])  # both trigger STO deadline rules

CHANNEL_SMS = "1207562370794990"
CHANNEL_PUSH = "1207562370794991"

# Brand GID → code
BRAND_GID_TO_CODE = {
    "1207522425689881": "HAV",
    "1207553690167887": "CZ",
    "1207522425689882": "ID",
    "1208572919795447": "BUR",
    "1207522425689883": "TI",
    "1207881071843537": "STF",
    "1208130746998739": "TRADE",
}

# Business hours
ET = ZoneInfo("America/New_York")
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18
BUSINESS_DAY_HOURS = BUSINESS_END_HOUR - BUSINESS_START_HOUR  # 9
LAUNCH_HOUR = 8  # campaigns send at 8 AM ET, before business day starts at 9 AM

# SLA threshold: 2 business days = 18 business hours
SLA_HOURS = float(BUSINESS_DAY_HOURS * 2)

# Holiday calendar
HOLIDAYS: frozenset = frozenset([
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 7), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 24), date(2025, 12, 25), date(2025, 12, 26), date(2025, 12, 31),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3),
    date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 24),
    date(2026, 12, 25), date(2026, 12, 31),
])

# Status names (normalized lowercase, no color codes)
BUILD_START_STATUS = "ready to code"
QA_PROOF_STATUS = "qa proof sent"
BUILD_DONE_STATUSES = frozenset(["qa proof sent", "ready for qa", "ready to dispatch", "launched"])

# Ordered list of known statuses for endswith matching (longer/more-specific first)
_KNOWN_STATUSES = [
    "waiting on brief to be filled out",
    "ready to dispatch",
    "qa proof sent",
    "ready for qa",
    "awaiting creative",
    "awaiting approval",
    "ready to code",
    "launched",
]

COLOR_CODE_RE = re.compile(r"\s*\([A-Z][A-Z\-]*\)\s*$")
ASSIGN_RE = re.compile(r"assigned to (.+)", re.IGNORECASE)

# Output paths
CACHE_FILE = ROOT / "exports" / "asana_velocity_data.json"
SMS_PUSH_CACHE_FILE = ROOT / "exports" / "asana_velocity_data_sms_push.json"
DEFAULT_REPORT = ROOT / "reports" / "lifecycle-velocity-report.md"

# ---------------------------------------------------------------------------
# Business hours helpers
# ---------------------------------------------------------------------------


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def next_business_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def effective_start(dt: datetime) -> datetime:
    """Snap a datetime to the next valid business-hours moment (9 AM ET)."""
    dt_et = dt.astimezone(ET)
    d = dt_et.date()
    h = dt_et.hour

    if is_business_day(d) and BUSINESS_START_HOUR <= h < BUSINESS_END_HOUR:
        return dt_et

    if is_business_day(d) and h < BUSINESS_START_HOUR:
        return datetime(d.year, d.month, d.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)

    nd = next_business_day(d)
    return datetime(nd.year, nd.month, nd.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)


def business_hours_between(start: datetime, end: datetime) -> float:
    """Compute business hours between two datetimes (ET, 9–6 PM, Mon–Fri)."""
    if end <= start:
        return 0.0

    eff = effective_start(start)
    if end <= eff:
        return 0.0

    total_minutes = 0.0
    current = eff
    end_et = end.astimezone(ET)

    while current < end_et:
        d = current.date()

        if not is_business_day(d):
            nd = next_business_day(d)
            current = datetime(nd.year, nd.month, nd.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)
            continue

        day_end = datetime(d.year, d.month, d.day, BUSINESS_END_HOUR, 0, 0, tzinfo=ET)

        if end_et <= day_end:
            total_minutes += (end_et - current).total_seconds() / 60.0
            break
        else:
            total_minutes += (day_end - current).total_seconds() / 60.0
            nd = next_business_day(d)
            current = datetime(nd.year, nd.month, nd.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)

    return total_minutes / 60.0


def date_to_biz_days(d1: date, d2: date) -> float:
    """Business days between two dates (using start-of-day times)."""
    if d2 <= d1:
        return 0.0
    dt1 = datetime(d1.year, d1.month, d1.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)
    dt2 = datetime(d2.year, d2.month, d2.day, BUSINESS_START_HOUR, 0, 0, tzinfo=ET)
    return business_hours_between(dt1, dt2) / BUSINESS_DAY_HOURS


# ---------------------------------------------------------------------------
# Asana API client
# ---------------------------------------------------------------------------


class AsanaClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        })

    def get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        url = f"{ASANA_BASE_URL}/{endpoint}"
        resp = self.session.get(url, params=params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            print(f"  Rate limited — waiting {retry_after}s...", flush=True)
            time.sleep(retry_after)
            resp = self.session.get(url, params=params)

        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            return None

        return resp.json()

    def paginate(self, endpoint: str, params: Optional[dict] = None) -> list:
        params = dict(params or {})
        results = []

        while True:
            data = self.get(endpoint, params)
            if not data:
                break

            results.extend(data.get("data", []))
            next_page = data.get("next_page")
            if not next_page or not next_page.get("offset"):
                break

            params["offset"] = next_page["offset"]

        return results


# ---------------------------------------------------------------------------
# Custom field helpers
# ---------------------------------------------------------------------------


def get_enum_value_gid(task: dict, field_gid: str) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            ev = cf.get("enum_value")
            return ev.get("gid") if ev else None
    return None


def get_enum_value_name(task: dict, field_gid: str) -> Optional[str]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            ev = cf.get("enum_value")
            return ev.get("name") if ev else None
    return None


# ---------------------------------------------------------------------------
# Status change detection (bug-fixed: handles "from Waiting on Brief to be
# Filled Out to Ready to Code" and similar multi-"to" transitions)
# ---------------------------------------------------------------------------


def get_status_change(text: str) -> Optional[str]:
    """Extract the destination status from a Task Status change story.

    Matches the END of the story text against known status names to correctly
    handle statuses that contain the word "to" (e.g., "Ready to Code",
    "Waiting on Brief to be Filled Out").
    """
    tl = text.lower().strip()
    if "task status" not in tl or "changed" not in tl:
        return None

    # Strip trailing color codes like "(RED)", "(YELLOW-ORANGE)", "(YELLOW-GREEN)"
    cleaned = COLOR_CODE_RE.sub("", tl).rstrip()

    # Match the destination: text must end with " to <status>" (longest match first)
    for status in _KNOWN_STATUSES:
        if cleaned.endswith(f" to {status}"):
            return status

    return None


def classify_builder(name: Optional[str]) -> str:
    if not name:
        return "Other"
    n = name.lower()
    if "emmanuel" in n:
        return "Emmanuel"
    if "momina" in n:
        return "Momina"
    if "abdullah" in n:
        return "Abdullah"
    return "Other"


# ---------------------------------------------------------------------------
# Story parsing
# ---------------------------------------------------------------------------


def parse_task_timeline(stories: list) -> dict:
    """Extract key timestamps + builder attribution from task stories.

    Builder logic:
      1. Whoever set "QA Proof Sent" is the builder (they did the work).
      2. If no "QA Proof Sent" exists, the builder is the most recently
         assigned person (from assignment stories) before the build-done event.
      3. Last resort: whoever set the build-done status.

    Returns:
        ready_to_code_at, build_done_at, build_done_by, build_done_status,
        qa_proof_sent_at, qa_proof_sent_by
    """
    sorted_stories = sorted(stories, key=lambda s: s.get("created_at", ""))

    ready_to_code_at: Optional[datetime] = None
    qa_proof_sent_at: Optional[datetime] = None
    qa_proof_sent_by: Optional[str] = None
    build_done_at: Optional[datetime] = None      # only set when ready_to_code_at exists (SLA use)
    build_done_by: Optional[str] = None
    build_done_status: Optional[str] = None
    first_build_done_at: Optional[datetime] = None  # unconditional: any build-done status seen
    first_build_done_by: Optional[str] = None       # for assignment-fallback attribution
    first_build_done_status: Optional[str] = None
    last_assignee: Optional[str] = None  # most recent "assigned to X" before each event
    last_am_assigned_at: Optional[datetime] = None  # last A/M assignment before build-done

    for story in sorted_stories:
        text = story.get("text", "")
        ts = story.get("created_at", "")
        if not text or not ts:
            continue

        # Track assignment changes
        am = ASSIGN_RE.search(text)
        if am:
            last_assignee = am.group(1).strip()
            # Track when a builder was last assigned, but only before any build-done event
            # (post-build reassignments like handing to Savanna for review don't count)
            if classify_builder(last_assignee) in ("Abdullah", "Emmanuel", "Momina") and first_build_done_at is None:
                last_am_assigned_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            continue  # assignment stories don't carry status changes

        status = get_status_change(text)
        if not status:
            continue

        created_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        story_author = (story.get("created_by") or {}).get("name")

        if status == BUILD_START_STATUS:
            if ready_to_code_at is None:
                ready_to_code_at = created_at

        elif status == QA_PROOF_STATUS:
            if qa_proof_sent_at is None:
                qa_proof_sent_at = created_at
                qa_proof_sent_by = story_author

            # Unconditional first-build-done tracking (for assignment fallback)
            if first_build_done_at is None:
                first_build_done_at = created_at
                first_build_done_status = status
                first_build_done_by = qa_proof_sent_by

            # Also counts as build_done (guarded: only when RTC exists, for SLA)
            if ready_to_code_at is not None and build_done_at is None:
                build_done_at = created_at
                build_done_status = status
                # Builder = who set QA Proof Sent
                build_done_by = qa_proof_sent_by

        elif status in BUILD_DONE_STATUSES:
            # "ready to dispatch" or "launched"

            # Unconditional first-build-done tracking (for assignment fallback)
            if first_build_done_at is None:
                first_build_done_at = created_at
                first_build_done_status = status
                if last_assignee and classify_builder(last_assignee) in ("Abdullah", "Emmanuel", "Momina"):
                    first_build_done_by = last_assignee
                else:
                    first_build_done_by = story_author

            # Guarded: only count toward SLA when RTC exists
            if ready_to_code_at is not None and build_done_at is None:
                build_done_at = created_at
                build_done_status = status

                # Builder attribution: prefer last assignee if it's a known builder
                # (they built it; Savanna/Grace/Mina may have set the final status)
                if last_assignee and classify_builder(last_assignee) in ("Abdullah", "Emmanuel", "Momina"):
                    build_done_by = last_assignee
                else:
                    build_done_by = story_author

    return {
        "ready_to_code_at": ready_to_code_at,
        "build_done_at": build_done_at,
        "build_done_by": build_done_by,
        "build_done_status": build_done_status,
        "first_build_done_at": first_build_done_at,
        "first_build_done_by": first_build_done_by,
        "first_build_done_status": first_build_done_status,
        "qa_proof_sent_at": qa_proof_sent_at,
        "qa_proof_sent_by": qa_proof_sent_by,
        "builder_assigned_at": last_am_assigned_at,
    }


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

_TASK_OPT_FIELDS = ",".join([
    "gid", "name",
    "assignee.name",
    "completed", "completed_at",
    "created_at", "modified_at",
    "due_on",
    "custom_fields.gid",
    "custom_fields.name",
    "custom_fields.enum_value.name",
    "custom_fields.enum_value.gid",
    "custom_fields.display_value",
])

_STORY_OPT_FIELDS = "type,resource_subtype,created_at,created_by.name,text"


def fetch_and_cache(
    client: AsanaClient,
    output_path: Path,
    since: Optional[str] = None,
    channel_gids: Optional[list] = None,
) -> None:
    """Fetch tasks + stories from Asana and save to JSON cache.

    Args:
        since: ISO date string — only fetch tasks completed on/after this date.
        channel_gids: List of FIELD_CHANNEL enum GIDs to include.
                      Defaults to [CHANNEL_EMAIL].
    """
    if channel_gids is None:
        channel_gids = [CHANNEL_EMAIL]
    completed_since = since or "2024-01-01"
    print(f"Fetching project tasks from Asana (paginated, completed_since={completed_since})...")
    all_tasks = client.paginate(
        f"projects/{ASANA_PROJECT_GID}/tasks",
        params={
            "opt_fields": _TASK_OPT_FIELDS,
            "completed_since": completed_since,
            "limit": 100,
        },
    )
    print(f"  Total project tasks: {len(all_tasks)}")

    channel_tasks = [
        t for t in all_tasks
        if get_enum_value_gid(t, FIELD_CHANNEL) in channel_gids
    ]
    channel_label = "+".join(
        {CHANNEL_EMAIL: "email", CHANNEL_SMS: "sms", CHANNEL_PUSH: "push"}.get(g, g)
        for g in channel_gids
    )
    print(f"  {channel_label.title()} tasks: {len(channel_tasks)}")

    result = []
    total = len(channel_tasks)
    for i, task in enumerate(channel_tasks, 1):
        if i % 25 == 0 or i == total:
            print(f"  Fetching stories: {i}/{total}...", flush=True)

        stories = client.paginate(
            f"tasks/{task['gid']}/stories",
            params={"opt_fields": _STORY_OPT_FIELDS, "limit": 100},
        )
        result.append({"task": task, "stories": stories})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\nCached {len(result)} {channel_label} tasks with stories → {output_path}")


def patch_due_on(client: AsanaClient, cache_path: Path) -> None:
    """Fast update: fetch due_on for all project tasks and patch the cache.

    Much faster than --fetch since it only needs the project tasks list
    (one paginated call, no per-task story fetches).
    """
    print("Fetching task due_on values from Asana...")
    all_tasks = client.paginate(
        f"projects/{ASANA_PROJECT_GID}/tasks",
        params={
            "opt_fields": "gid,due_on",
            "completed_since": "2024-01-01",
            "limit": 100,
        },
    )
    due_on_map = {t["gid"]: t.get("due_on") for t in all_tasks}
    print(f"  Fetched due_on for {len(due_on_map)} tasks")

    print(f"Patching cache at {cache_path}...")
    with open(cache_path) as f:
        data = json.load(f)

    updated = 0
    for entry in data:
        gid = entry["task"]["gid"]
        if gid in due_on_map:
            entry["task"]["due_on"] = due_on_map[gid]
            updated += 1

    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"  Updated {updated} cache entries with due_on")


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def compute_task_metrics(entry: dict, exclude_sto: bool = True) -> Optional[dict]:
    """Compute velocity metrics for one task.

    Returns None if the task should be excluded entirely (flow task, STO test).
    Otherwise returns a dict with status: "complete", "in_progress", or
    "no_ready_to_code".

    Args:
        exclude_sto: If True (default), STO Test tasks are excluded (return None).
            Pass False in the velocity dashboard to include STO tasks with a
            different deadline calculation (is_sto_test=True in the returned dict).
    """
    task = entry["task"]
    stories = entry["stories"]

    # --- Filters ---
    # Exclude triggered journey (flow/lifecycle) tasks
    if get_enum_value_gid(task, FIELD_TYPE) == TYPE_TRIGGERED_JOURNEY:
        return None
    # STO Test? = Yes or Test
    is_sto_test = get_enum_value_gid(task, FIELD_STO_TEST) in STO_TEST_GIDS
    if exclude_sto and is_sto_test:
        return None

    gid = task.get("gid", "")
    name = task.get("name", "")
    completed_at_str = task.get("completed_at")
    assignee_name = (task.get("assignee") or {}).get("name")
    due_on_str = task.get("due_on")  # "YYYY-MM-DD" or None

    brand_gid = get_enum_value_gid(task, FIELD_BRAND)
    brand = BRAND_GID_TO_CODE.get(brand_gid, "Unknown") if brand_gid else "Unknown"

    timeline = parse_task_timeline(stories)
    rtc = timeline["ready_to_code_at"]
    done = timeline["build_done_at"]
    done_by = timeline["build_done_by"]
    done_status = timeline["build_done_status"]

    # Fallback: completed task with no explicit build-done status
    if rtc is not None and done is None and completed_at_str:
        completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
        if completed_at > rtc:
            done = completed_at
            done_by = assignee_name
            done_status = "completed"

    # Assignment-start fallback: no Ready to Code, but task was assigned to a builder
    # before the build-done event → use that assignment time as the start.
    # Note: we use first_build_done_at (tracked unconditionally) because build_done_at
    # is guarded by ready_to_code_at is not None, so it's always None for no-RTC tasks.
    builder_assigned_at = timeline.get("builder_assigned_at")
    first_bd_at = timeline.get("first_build_done_at")
    start_type = "ready_to_code"
    if rtc is None and first_bd_at is not None and builder_assigned_at is not None:
        if builder_assigned_at < first_bd_at:
            rtc = builder_assigned_at
            done = first_bd_at
            done_by = timeline.get("first_build_done_by") or done_by
            done_status = timeline.get("first_build_done_status") or done_status
            start_type = "assignment"

    builder_group = classify_builder(done_by)

    base = {
        "gid": gid,
        "name": name,
        "brand": brand,
        "builder_raw": done_by,
        "builder_group": builder_group,
        "current_assignee_name": assignee_name,  # current task assignee (for in-progress attribution)
        "is_sto_test": is_sto_test,
        "due_on": due_on_str,
        "start_type": start_type,
    }

    if rtc is None:
        return {**base,
                "ready_to_code_at": None,
                "build_done_at": None,
                "build_hours": None,
                "build_days": None,
                "sla_breach": None,
                "done_status": None,
                "status": "no_ready_to_code"}

    if done is None:
        return {**base,
                "ready_to_code_at": rtc.isoformat(),
                "build_done_at": None,
                "build_hours": None,
                "build_days": None,
                "sla_breach": None,
                "done_status": None,
                "status": "in_progress"}

    hours = business_hours_between(rtc, done)
    days = hours / BUSINESS_DAY_HOURS

    return {**base,
            "ready_to_code_at": rtc.isoformat(),
            "build_done_at": done.isoformat(),
            "build_hours": round(hours, 2),
            "build_days": round(days, 3),
            "sla_breach": hours >= SLA_HOURS,
            "done_status": done_status,
            "status": "complete"}


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def percentile(data: list, p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo = int(idx)
    hi = lo + 1
    if hi >= len(s):
        return s[-1]
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def group_stats(metrics: list) -> Optional[dict]:
    complete = [m for m in metrics if m["status"] == "complete"]
    if not complete:
        return None

    hours_list = [m["build_hours"] for m in complete]
    days_list = [m["build_days"] for m in complete]
    breaches = [m for m in complete if m["sla_breach"]]

    return {
        "count": len(complete),
        "avg_hours": round(mean(hours_list), 1),
        "median_hours": round(median(hours_list), 1),
        "p90_hours": round(percentile(hours_list, 90), 1),
        "max_hours": round(max(hours_list), 1),
        "avg_days": round(mean(days_list), 2),
        "median_days": round(median(days_list), 2),
        "p90_days": round(percentile(days_list, 90), 2),
        "max_days": round(max(days_list), 2),
        "breach_count": len(breaches),
        "breach_pct": round(len(breaches) / len(complete) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Lead-time analysis helpers
# ---------------------------------------------------------------------------


def lead_time_bucket(days: float) -> str:
    if days < 4:
        return "3–4 days"
    if days < 5:
        return "4–5 days"
    if days < 7:
        return "5–7 days"
    if days < 10:
        return "7–10 days"
    return "10+ days"


BUCKET_ORDER = ["3–4 days", "4–5 days", "5–7 days", "7–10 days", "10+ days"]


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def fmt_dt(iso: str, fmt: str = "%Y-%m-%d") -> str:
    return datetime.fromisoformat(iso).strftime(fmt)


def build_report(all_metrics: list, days_filter: int, output_path: Path) -> None:
    now_utc = datetime.now(tz=timezone.utc)
    cutoff = now_utc - timedelta(days=days_filter)

    no_rtc = [m for m in all_metrics if m["status"] == "no_ready_to_code"]
    in_progress = [m for m in all_metrics if m["status"] == "in_progress"]

    complete = []
    for m in all_metrics:
        if m["status"] != "complete" or not m["ready_to_code_at"]:
            continue
        rtc = datetime.fromisoformat(m["ready_to_code_at"])
        if rtc >= cutoff:
            complete.append(m)

    lines = []
    period_start = cutoff.strftime("%B %d, %Y")
    period_end = now_utc.strftime("%B %d, %Y")
    lines.append("# Lifecycle Velocity Report\n\n")
    lines.append(
        f"*Generated: {now_utc.strftime('%B %d, %Y')} · "
        f"Period: {period_start} → {period_end} ({days_filter} days)*\n\n"
    )

    if not complete:
        lines.append("No completed build cycles found in the analysis window.\n")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(lines))
        print(f"Report saved to {output_path} (no data)")
        return

    overall = group_stats(complete)
    breaches = [m for m in complete if m["sla_breach"]]
    assignment_start = [m for m in complete if m.get("start_type") == "assignment"]

    # ── 1. Executive Summary ──────────────────────────────────────────────
    lines.append("## Executive Summary\n\n")
    lines.append("| Metric | Value |\n|--------|-------|\n")
    lines.append(f"| Email campaigns with full build history | **{overall['count']}** |\n")
    if assignment_start:
        lines.append(
            f"| ↳ Using assignment time as start (no Ready to Code status) | {len(assignment_start)} |\n"
        )
    lines.append(
        f"| Median build time | **{overall['median_days']:.2f} biz days** ({overall['median_hours']:.1f} hrs) |\n"
    )
    lines.append(
        f"| Average build time | {overall['avg_days']:.2f} biz days ({overall['avg_hours']:.1f} hrs) |\n"
    )
    lines.append(
        f"| 90th percentile build time | {overall['p90_days']:.2f} biz days ({overall['p90_hours']:.1f} hrs) |\n"
    )
    lines.append(
        f"| **SLA breach rate** (≥2 biz days) | **{overall['breach_count']} / {overall['count']} ({overall['breach_pct']}%)** |\n"
    )
    lines.append(f"| Campaigns in progress (Ready to Code, not yet built) | {len(in_progress)} |\n")
    lines.append(
        f"| Tasks with no resolvable start time | {len(no_rtc)} |\n"
    )
    lines.append("\n")

    # ── 2. Overall Performance ─────────────────────────────────────────────
    lines.append("## Overall Build Performance\n\n")
    lines.append("| Metric | Business Hours | Business Days |\n|--------|---------------|---------------|\n")
    lines.append(f"| Average | {overall['avg_hours']:.1f} | {overall['avg_days']:.2f} |\n")
    lines.append(f"| Median | {overall['median_hours']:.1f} | {overall['median_days']:.2f} |\n")
    lines.append(f"| 90th percentile | {overall['p90_hours']:.1f} | {overall['p90_days']:.2f} |\n")
    lines.append(f"| Maximum | {overall['max_hours']:.1f} | {overall['max_days']:.2f} |\n")
    lines.append("\n")

    # ── 3. By Builder ──────────────────────────────────────────────────────
    lines.append("## Performance by Builder\n\n")
    lines.append(
        "| Builder | Tasks | Avg Days | Median Days | p90 Days | SLA Breaches |\n"
        "|---------|-------|----------|-------------|----------|--------------|\n"
    )
    for group in ["Abdullah", "Momina", "Other"]:
        g = [m for m in complete if m["builder_group"] == group]
        if not g:
            lines.append(f"| {group} | 0 | — | — | — | — |\n")
            continue
        s = group_stats(g)
        lines.append(
            f"| {group} | {s['count']} | {s['avg_days']:.2f} | {s['median_days']:.2f} "
            f"| {s['p90_days']:.2f} | {s['breach_count']} ({s['breach_pct']}%) |\n"
        )
    lines.append("\n")

    # Other builders breakdown
    other_tasks = [m for m in complete if m["builder_group"] == "Other"]
    if other_tasks:
        by_name: dict = defaultdict(list)
        for m in other_tasks:
            by_name[m["builder_raw"] or "(unassigned)"].append(m)
        lines.append("### Other Builders Detail\n\n")
        lines.append(
            "| Name | Tasks | Avg Days | Median Days | SLA Breaches |\n"
            "|------|-------|----------|-------------|--------------|\n"
        )
        for name, tasks in sorted(by_name.items(), key=lambda x: -len(x[1])):
            s = group_stats(tasks)
            lines.append(
                f"| {name} | {s['count']} | {s['avg_days']:.2f} | {s['median_days']:.2f} "
                f"| {s['breach_count']} ({s['breach_pct']}%) |\n"
            )
        lines.append("\n")

    # ── 4. By Brand ────────────────────────────────────────────────────────
    lines.append("## Performance by Brand\n\n")
    lines.append(
        "| Brand | Tasks | Avg Days | Median Days | SLA Breaches |\n"
        "|-------|-------|----------|-------------|--------------|\n"
    )
    by_brand: dict = defaultdict(list)
    for m in complete:
        by_brand[m["brand"]].append(m)
    for brand in sorted(by_brand.keys(), key=lambda b: -len(by_brand[b])):
        s = group_stats(by_brand[brand])
        lines.append(
            f"| {brand} | {s['count']} | {s['avg_days']:.2f} | {s['median_days']:.2f} "
            f"| {s['breach_count']} ({s['breach_pct']}%) |\n"
        )
    lines.append("\n")

    # ── 5. Monthly Trends ─────────────────────────────────────────────────
    lines.append("## Monthly Trends\n\n")
    lines.append(
        "| Month | Tasks | Avg Days | Median Days | SLA Breaches | Breach % |\n"
        "|-------|-------|----------|-------------|--------------|----------|\n"
    )
    by_month: dict = defaultdict(list)
    for m in complete:
        by_month[datetime.fromisoformat(m["ready_to_code_at"]).strftime("%Y-%m")].append(m)
    for month in sorted(by_month.keys()):
        s = group_stats(by_month[month])
        label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        lines.append(
            f"| {label} | {s['count']} | {s['avg_days']:.2f} | {s['median_days']:.2f} "
            f"| {s['breach_count']} | {s['breach_pct']}% |\n"
        )
    lines.append("\n")

    # ── 6. Monthly by Builder ─────────────────────────────────────────────
    lines.append("## Monthly Trends by Builder\n\n")
    for group in ["Abdullah", "Momina"]:
        g_tasks = [m for m in complete if m["builder_group"] == group]
        if not g_tasks:
            continue
        lines.append(f"### {group}\n\n")
        lines.append(
            "| Month | Tasks | Avg Days | Median Days | SLA Breaches |\n"
            "|-------|-------|----------|-------------|--------------|\n"
        )
        by_month_g: dict = defaultdict(list)
        for m in g_tasks:
            by_month_g[datetime.fromisoformat(m["ready_to_code_at"]).strftime("%Y-%m")].append(m)
        for month in sorted(by_month_g.keys()):
            s = group_stats(by_month_g[month])
            label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            lines.append(
                f"| {label} | {s['count']} | {s['avg_days']:.2f} | {s['median_days']:.2f} "
                f"| {s['breach_count']} ({s['breach_pct']}%) |\n"
            )
        lines.append("\n")

    # ── 7. Materials Lead Time Analysis ───────────────────────────────────
    lines.append("## Materials Lead Time Analysis\n\n")
    lines.append(
        "*How long before the scheduled send date were materials approved (Ready to Code)?*\n"
        "*For tasks with ≥3 business days of advance notice, how quickly did builds actually happen?*\n\n"
    )

    lead_tasks = []
    for m in complete:
        if not m["due_on"] or not m["ready_to_code_at"] or not m["build_done_at"]:
            continue
        due = date.fromisoformat(m["due_on"])
        rtc_dt = datetime.fromisoformat(m["ready_to_code_at"])
        done_dt = datetime.fromisoformat(m["build_done_at"])
        rtc_date = rtc_dt.astimezone(ET).date()

        # Launch is at 8 AM ET on due_on (before business day starts at 9 AM)
        launch_dt = datetime(due.year, due.month, due.day, LAUNCH_HOUR, 0, 0, tzinfo=ET)

        # Lead = business hours from RTC approval to 8 AM launch
        lead = business_hours_between(rtc_dt, launch_dt) / BUSINESS_DAY_HOURS
        if lead < 3.0:
            continue

        # Remaining = business hours from build submission to 8 AM launch
        # If build done after 6 PM and launch is 8 AM next day, effective_start snaps
        # to 9 AM which is past the 8 AM launch → correctly returns 0.0 hours
        remaining = business_hours_between(done_dt, launch_dt) / BUSINESS_DAY_HOURS
        # Clamp negative (build done after launch time)
        remaining = max(remaining, -5.0)

        lead_tasks.append({
            **m,
            "lead_time_days": round(lead, 2),
            "remaining_days": round(remaining, 2),
            "bucket": lead_time_bucket(lead),
        })

    if not lead_tasks:
        lines.append("*No tasks with due_on data found. Run `--patch-due-on` to add due dates to cache.*\n\n")
    else:
        # Overall lead-time summary
        total_lead = len(lead_tasks)
        lines.append(
            f"**{total_lead} campaigns** had materials ready ≥3 business days before the scheduled send date.\n\n"
        )

        # Key finding: days remaining after build submission
        remaining_vals = [t["remaining_days"] for t in lead_tasks]
        pct_last_day = sum(1 for r in remaining_vals if r < 1.0) / len(remaining_vals) * 100

        lines.append(
            f"- Median days remaining after build submission: **{median(remaining_vals):.1f} biz days**\n"
        )
        lines.append(
            f"- **{pct_last_day:.0f}%** of builds were submitted with less than 1 business day before launch\n\n"
        )

        # By lead-time bucket
        lines.append("### Build Speed by Materials Lead Time\n\n")
        lines.append(
            "| Materials advance notice | Tasks | Avg build time | Median build time | "
            "Avg days left after build | % builds <1 day before launch |\n"
            "|--------------------------|-------|----------------|-------------------|"
            "--------------------------|--------------------------------|\n"
        )

        by_bucket: dict = defaultdict(list)
        for t in lead_tasks:
            by_bucket[t["bucket"]].append(t)

        for bucket in BUCKET_ORDER:
            tasks = by_bucket.get(bucket, [])
            if not tasks:
                continue
            build_days_list = [t["build_days"] for t in tasks]
            rem_list = [t["remaining_days"] for t in tasks]
            pct_rushed = sum(1 for r in rem_list if r < 1.0) / len(tasks) * 100
            lines.append(
                f"| {bucket} | {len(tasks)} | {mean(build_days_list):.2f}d | {median(build_days_list):.2f}d "
                f"| {mean(rem_list):.2f}d | {pct_rushed:.0f}% |\n"
            )
        lines.append("\n")

        # The "idle time" framing
        lines.append("### The Deadline Pattern\n\n")
        lines.append(
            "*Regardless of how much advance notice was given, builds consistently finish with ~1 business day "
            "remaining before launch. This means the larger the lead time, the longer the build sits waiting to "
            "be started — all available time eventually gets used.*\n\n"
        )
        lines.append(
            "| Materials advance | Avg lead time | Avg build 'finish' before launch | % of lead time consumed |\n"
            "|-------------------|---------------|----------------------------------|-------------------------|\n"
        )
        for bucket in BUCKET_ORDER:
            tasks = by_bucket.get(bucket, [])
            if not tasks:
                continue
            lead_list = [t["lead_time_days"] for t in tasks]
            rem_list = [t["remaining_days"] for t in tasks]
            avg_lead = mean(lead_list)
            avg_rem = mean(rem_list)
            pct_consumed = (avg_lead - avg_rem) / avg_lead * 100 if avg_lead > 0 else 0
            lines.append(
                f"| {bucket} | {avg_lead:.1f}d | {avg_rem:.2f}d before launch "
                f"| {pct_consumed:.0f}% |\n"
            )
        lines.append("\n")

    # ── 8. SLA Breach Detail ──────────────────────────────────────────────
    lines.append("## SLA Breach Detail\n\n")
    lines.append(
        f"*Campaigns where build time ≥ {SLA_HOURS:.0f} business hours (2 business days). "
        f"{len(breaches)} total.*\n\n"
    )

    if not breaches:
        lines.append("*No SLA breaches in this analysis window.*\n\n")
    else:
        breaches_sorted = sorted(breaches, key=lambda m: -(m["build_days"] or 0))
        lines.append(
            "| Task | Brand | Builder | Ready to Code | Build Done | Biz Days | Status |\n"
            "|------|-------|---------|---------------|------------|----------|--------|\n"
        )
        for m in breaches_sorted:
            rtc_str = fmt_dt(m["ready_to_code_at"])
            done_str = fmt_dt(m["build_done_at"])
            short_name = (m["name"][:55] + "…") if len(m["name"]) > 55 else m["name"]
            lines.append(
                f"| {short_name} | {m['brand']} | {m['builder_group']} "
                f"| {rtc_str} | {done_str} | **{m['build_days']:.1f}** | {m['done_status'] or '—'} |\n"
            )
    lines.append("\n")

    # ── 9. Data Coverage ──────────────────────────────────────────────────
    lines.append("## Data Coverage\n\n")
    lines.append(
        f"- **{overall['count']}** campaigns have complete build history in the analysis window\n"
    )
    if assignment_start:
        lines.append(
            f"  - **{len(assignment_start)}** of those used assignment-to-builder time as start "
            f"(task skipped 'Ready to Code' status — time measured from when Abdullah/Momina was assigned)\n"
        )
    lines.append(f"- **{len(in_progress)}** campaigns are currently in progress (Ready to Code, not yet built)\n")
    lines.append(
        f"- **{len(no_rtc)}** email tasks have no resolvable start time\n"
        f"  *(no 'Ready to Code' status AND no builder assignment found — likely pre-workflow historical tasks)*\n"
    )
    lines.append(
        "\n*Business hours: 9 AM – 6 PM ET, Mon–Fri, excluding company holidays.*\n"
        "*Builder attribution: person who set QA Proof Sent (the actual build action), "
        "or last task assignee before build-done if no QA Proof Sent story exists.*\n"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines))

    print(f"\nReport saved to {output_path}")
    print(f"  {overall['count']} completed build cycles")
    print(f"  Median build time: {overall['median_days']:.2f} biz days")
    print(f"  SLA breaches: {overall['breach_count']} ({overall['breach_pct']}%)")
    if lead_tasks:
        print(f"  Lead-time analysis: {len(lead_tasks)} tasks with 3+ days advance notice")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lifecycle Velocity Tracker — email build time analysis"
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Pull fresh data from Asana (saves to exports/asana_velocity_data.json)",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="Only fetch tasks completed on/after this date (YYYY-MM-DD). "
             "E.g. --since 2026-02-07 to fetch ~1 month. Defaults to 2024-01-01 (all history).",
    )
    parser.add_argument(
        "--patch-due-on", action="store_true", dest="patch_due_on",
        help="Fast update: fetch task due dates and patch into existing cache (~30s)",
    )
    parser.add_argument(
        "--fetch-sms-push", action="store_true", dest="fetch_sms_push",
        help="Pull SMS + Push task data from Asana (saves to exports/asana_velocity_data_sms_push.json)",
    )
    parser.add_argument(
        "--days", type=int, default=180,
        help="Analysis window in days (default: 180)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_REPORT,
        help="Output report path",
    )
    args = parser.parse_args()

    if args.fetch or args.patch_due_on or args.fetch_sms_push:
        token = os.environ.get("ASANA_ACCESS_TOKEN")
        if not token:
            print("Error: ASANA_ACCESS_TOKEN not set in .env")
            sys.exit(1)
        client = AsanaClient(token)

        if args.fetch:
            fetch_and_cache(client, CACHE_FILE, since=args.since)
        if args.patch_due_on:
            if not CACHE_FILE.exists():
                print(f"Error: No cache at {CACHE_FILE}. Run --fetch first.")
                sys.exit(1)
            patch_due_on(client, CACHE_FILE)
        if args.fetch_sms_push:
            fetch_and_cache(
                client, SMS_PUSH_CACHE_FILE, since=args.since,
                channel_gids=[CHANNEL_SMS, CHANNEL_PUSH],
            )

    if not CACHE_FILE.exists():
        print(f"Error: No cached data at {CACHE_FILE}")
        print("Run with --fetch to pull from Asana first.")
        sys.exit(1)

    print(f"Loading {CACHE_FILE}...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    print(f"  {len(data)} email task records")

    print("Computing metrics...")
    all_metrics_raw = [compute_task_metrics(entry) for entry in data]
    all_metrics = [m for m in all_metrics_raw if m is not None]

    complete_count = sum(1 for m in all_metrics if m["status"] == "complete")
    in_progress_count = sum(1 for m in all_metrics if m["status"] == "in_progress")
    no_rtc_count = sum(1 for m in all_metrics if m["status"] == "no_ready_to_code")
    excluded = len(all_metrics_raw) - len(all_metrics)
    print(
        f"  Complete: {complete_count}, In progress: {in_progress_count}, "
        f"No RTC: {no_rtc_count}, Excluded (flow/STO): {excluded}"
    )

    build_report(all_metrics, args.days, args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Weekly Velocity Dashboard — posts Asana project status update.

Reads from the lifecycle velocity tracker cache and posts a formatted
velocity report to a private Asana project (VELOCITY_PROJECT_GID in .env).

Sections:
  1. Current backlog: in-progress builds by builder + 5-day rolling average
  2. Last week's completed builds (by builder, with last-minute metric)
  3. This week so far

STO tests are included but use a different deadline (3 calendar days before
send, snapped back to nearest business day), so their lead-time and
last-minute metrics are computed against that deadline.

Setup:
  1. Create a private Asana project (e.g. "Email Ops")
  2. Add its GID to .env as VELOCITY_PROJECT_GID=<gid>
  3. Run: uv run python scripts/braze_automation/post_velocity_dashboard.py --dry-run

Usage:
    uv run python scripts/braze_automation/post_velocity_dashboard.py [options]

Options:
    --dry-run       Print HTML instead of posting to Asana
    --refresh       Run --patch-due-on first to update due dates (~30s)
    --project-gid   Override VELOCITY_PROJECT_GID env var
"""

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Optional

import requests
from dotenv import load_dotenv

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
sys.path.insert(0, str(ROOT / "scripts"))

load_dotenv(ROOT / ".env")

# ── Import from lifecycle_velocity_tracker ────────────────────────────────────
from lifecycle_velocity_tracker import (  # noqa: E402
    ASANA_PROJECT_GID,
    BRAND_GID_TO_CODE,
    BUSINESS_DAY_HOURS,
    BUSINESS_END_HOUR,
    CACHE_FILE,
    SMS_PUSH_CACHE_FILE,
    FIELD_BRAND,
    FIELD_CHANNEL,
    FIELD_TYPE,
    FIELD_STO_TEST,
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_PUSH,
    TYPE_TRIGGERED_JOURNEY,
    STO_TEST_YES,
    STO_TEST_GIDS,
    ET,
    HOLIDAYS,
    LAUNCH_HOUR,
    AsanaClient,
    business_hours_between,
    classify_builder,
    compute_task_metrics,
    effective_start,
    get_enum_value_gid,
    is_business_day,
    next_business_day,
    parse_task_timeline,
    patch_due_on,
)

import json

ASANA_BASE_URL = "https://app.asana.com/api/1.0"


# ── DPS/MP double-counting ────────────────────────────────────────────────────

def task_weight(m: dict) -> int:
    """HAV 'DPS and MP' / 'MP and DPS' tasks count as 2 builds (2 separate audiences)."""
    name = (m.get("name") or "").lower()
    return 2 if ("dps and mp" in name or "mp and dps" in name) else 1


# ── STO deadline logic ────────────────────────────────────────────────────────

def sto_deadline_date(send_date: date) -> date:
    """Business day by which an STO test must be submitted.

    Rule: 3 calendar days before the send date, snapped back to the
    nearest business day (Mon–Fri, excluding holidays).

    Examples:
        Saturday send → Wednesday  (3 days before)
        Sunday send   → Thursday   (3 days before)
        Monday send   → Friday     (3 days before = Saturday → Friday)
        Tuesday send  → Friday     (3 days before = Saturday → Friday)
        Wednesday send → Friday    (3 days before = Sunday  → Friday)
        Thursday send  → Monday    (3 days before)
        Friday send    → Tuesday   (3 days before)
    """
    target = send_date - timedelta(days=3)
    while target.weekday() >= 5 or target in HOLIDAYS:
        target -= timedelta(days=1)
    return target


def task_deadline_dt(m: dict) -> Optional[datetime]:
    """Return the effective deadline datetime for a task.

    STO tests: 6 PM ET on sto_deadline_date(due_on).
    Regular:   8 AM ET on due_on (campaign send time).
    Returns None if due_on is not set.
    """
    due_on_str = m.get("due_on")
    if not due_on_str:
        return None
    due = date.fromisoformat(due_on_str)
    if m.get("is_sto_test"):
        d = sto_deadline_date(due)
        return datetime(d.year, d.month, d.day, BUSINESS_END_HOUR, 0, 0, tzinfo=ET)
    return datetime(due.year, due.month, due.day, LAUNCH_HOUR, 0, 0, tzinfo=ET)


# ── Week helpers ──────────────────────────────────────────────────────────────

def week_bounds(offset: int = 0) -> tuple[date, date]:
    """Mon–Sun bounds for a given week. offset=0=this week, -1=last week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_last_n_business_days(n: int) -> list[date]:
    """Last n completed business days (not including today), sorted ascending."""
    days: list[date] = []
    d = date.today() - timedelta(days=1)
    while len(days) < n:
        if is_business_day(d):
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


# ── Metric computation ────────────────────────────────────────────────────────

def week_tasks(all_metrics: list, week_start: date, week_end: date) -> list:
    """Tasks whose build was completed (build_done_at) within the week."""
    result = []
    for m in all_metrics:
        if m["status"] != "complete" or not m.get("build_done_at"):
            continue
        done_date = datetime.fromisoformat(m["build_done_at"]).astimezone(ET).date()
        if week_start <= done_date <= week_end:
            result.append(m)
    return result


def builder_week_stats(tasks: list) -> Optional[dict]:
    """Aggregate build-time stats for a list of completed tasks.

    DPS+MP tasks count as 2 builds (each audience counts separately).
    """
    if not tasks:
        return None
    hours: list[float] = []
    for m in tasks:
        w = task_weight(m)
        h = m.get("build_hours")
        if h is not None:
            hours.extend([h] * w)
    total_count = sum(task_weight(m) for m in tasks)
    if not hours:
        return {"count": total_count, "avg_days": 0.0, "median_days": 0.0}
    return {
        "count": total_count,
        "avg_days": round(mean(hours) / BUSINESS_DAY_HOURS, 2),
        "median_days": round(median(hours) / BUSINESS_DAY_HOURS, 2),
    }


def compute_lead_time_flags(tasks: list) -> dict:
    """For tasks with due_on, compute lead-time and last-minute flags.

    Returns a dict keyed by task gid: {lead_days, remaining_days, last_minute}.
    Only includes tasks with ≥3 business days of advance notice.
    """
    flags = {}
    for m in tasks:
        if not m.get("ready_to_code_at") or not m.get("build_done_at"):
            continue
        deadline = task_deadline_dt(m)
        if not deadline:
            continue
        rtc_dt = datetime.fromisoformat(m["ready_to_code_at"])
        done_dt = datetime.fromisoformat(m["build_done_at"])
        lead = business_hours_between(rtc_dt, deadline) / BUSINESS_DAY_HOURS
        if lead < 3.0:
            continue
        remaining = max(
            business_hours_between(done_dt, deadline) / BUSINESS_DAY_HOURS,
            -5.0,
        )
        flags[m["gid"]] = {
            "lead_days": lead,
            "remaining_days": remaining,
            "last_minute": remaining < 1.0 and lead >= 1.0,
        }
    return flags


def backlog_counts_at(all_metrics: list, as_of: datetime, builder: str) -> tuple[int, int]:
    """In-progress task counts for a builder as of a given moment.

    Returns (in_progress_count, stale_1day_count).
    Uses current_assignee_name as attribution proxy.

    For rolling averages, pass end-of-business-day (6 PM ET).
    For the current snapshot, pass datetime.now(tz=ET).
    """
    in_progress = 0
    stale = 0

    for m in all_metrics:
        rtc_str = m.get("ready_to_code_at")
        if not rtc_str:
            continue
        # Task must be attributed to this builder
        if classify_builder(m.get("current_assignee_name")) != builder:
            continue
        rtc_dt = datetime.fromisoformat(rtc_str)
        if rtc_dt > as_of:
            continue  # RTC not yet set at this point in time

        done_str = m.get("build_done_at")
        if done_str:
            done_dt = datetime.fromisoformat(done_str)
            if done_dt <= as_of:
                continue  # already done by this point

        in_progress += 1
        if business_hours_between(rtc_dt, as_of) >= BUSINESS_DAY_HOURS:
            stale += 1

    return in_progress, stale


# ── HTML generation ───────────────────────────────────────────────────────────

def _fmt_delta(val: float, prev: float, fmt: str = ".1f", unit: str = "") -> str:
    """Format a delta vs previous value, e.g. '(↑0.3d)' or '(↓2)'."""
    delta = val - prev
    if abs(delta) < 0.05:
        return ""
    arrow = "↑" if delta > 0 else "↓"
    return f" ({arrow}{abs(delta):{fmt}}{unit})"


def build_text(all_metrics: list, last_week: tuple, prior_week: tuple) -> str:
    """Build a plain-text status update (Asana project statuses don't render html_text)."""
    lw_start, lw_end = last_week
    pw_start, pw_end = prior_week
    now_et = datetime.now(tz=ET)

    lw_tasks = week_tasks(all_metrics, lw_start, lw_end)
    pw_tasks = week_tasks(all_metrics, pw_start, pw_end)

    lw_flags = compute_lead_time_flags(lw_tasks)

    past_5_days = get_last_n_business_days(5)

    lines = []

    # ── Lead-in: last-minute summary ──────────────────────────────────────────
    all_lw_lead = compute_lead_time_flags(lw_tasks)
    if all_lw_lead:
        lm_count = sum(1 for f in all_lw_lead.values() if f["last_minute"])
        n = len(all_lw_lead)
        lines.append(
            f"  {n} campaigns in the last 5 biz days had materials ready"
            f" 3+ biz days before the send date."
        )
        lines.append(
            f"  {lm_count} of {n}"
            f" ({int(lm_count / n * 100)}%) were submitted"
            f" with less than 1 biz day to spare before launch."
        )
        lines.append("")

    # ── Section 1: Current backlog ────────────────────────────────────────────
    lines.append("CURRENT BACKLOG (as of today)")
    for builder in ["Emmanuel", "Momina"]:
        cur_ip, cur_stale = backlog_counts_at(all_metrics, now_et, builder)

        ip_vals, stale_vals = [], []
        for d in past_5_days:
            d_eod = datetime(d.year, d.month, d.day, BUSINESS_END_HOUR, 0, 0, tzinfo=ET)
            ip, st = backlog_counts_at(all_metrics, d_eod, builder)
            ip_vals.append(ip)
            stale_vals.append(st)

        avg_ip = round(mean(ip_vals), 1) if ip_vals else 0.0
        avg_stale = round(mean(stale_vals), 1) if stale_vals else 0.0

        lines.append(
            f"  {builder} \u2014 In RTC: {cur_ip} (5-day avg: {avg_ip})"
            f"  \u00b7  Waiting 1+ biz day: {cur_stale} (5-day avg: {avg_stale})"
        )
    lines.append("  (5-day avg = count at 6 PM ET over the last 5 completed business days, excluding today)")

    # ── Section 2: Last 5 biz days vs prior 5 biz days ───────────────────────
    lines.append("")
    lines.append(
        f"LAST 5 BIZ DAYS \u2014 {lw_start.strftime('%b %d')}\u2013{lw_end.strftime('%b %d')}"
        f"  (prior: {pw_start.strftime('%b %d')}\u2013{pw_end.strftime('%b %d')})"
    )
    lines.append("")
    _append_week_rows(lines, lw_tasks, lw_flags, prev_tasks=pw_tasks)

    return "\n".join(lines)


def _append_week_rows(
    lines: list,
    tasks: list,
    flags: dict,
    prev_tasks: Optional[list] = None,
) -> None:
    """Append plain-text builder week stats — three sub-sections: all, 3+ days notice, short notice."""
    if not tasks:
        lines.append("  No completed builds in this period.")
        return

    # ── Speed sub-sections (Ready to Code → QA Proof Sent) ───────────────────
    lines.append("  BUILD SPEED (Ready to Code \u2192 QA Proof Sent)")
    lines.append("")

    # ── Sub-section A: All builds (with deltas vs prior week) ─────────────────
    lines.append("  All builds:")
    for builder in ["Emmanuel", "Momina"]:
        b_tasks = [m for m in tasks if m["builder_group"] == builder]
        s = builder_week_stats(b_tasks)
        delta_count, delta_avg = "", ""
        if prev_tasks and s:
            prev_b = [m for m in prev_tasks if m["builder_group"] == builder]
            ps = builder_week_stats(prev_b)
            if ps:
                delta_count = _fmt_delta(s["count"], ps["count"], fmt="0g")
                delta_avg = _fmt_delta(s["avg_days"], ps["avg_days"], unit="d")
        if s:
            lines.append(
                f"    {builder} \u2014 {s['count']} built{delta_count}"
                f"  \u00b7  Avg: {s['avg_days']:.1f}d{delta_avg}"
                f"  \u00b7  Median: {s['median_days']:.1f}d"
            )
        else:
            lines.append(f"    {builder} \u2014 0 built")
    total_s = builder_week_stats(tasks)
    if total_s:
        delta_total_count, delta_total_avg = "", ""
        if prev_tasks:
            prev_total = builder_week_stats(prev_tasks)
            if prev_total:
                delta_total_count = _fmt_delta(total_s["count"], prev_total["count"], fmt="0g")
                delta_total_avg = _fmt_delta(total_s["avg_days"], prev_total["avg_days"], unit="d")
        lines.append(
            f"    Total \u2014 {total_s['count']} built{delta_total_count}"
            f"  \u00b7  Avg: {total_s['avg_days']:.1f}d{delta_total_avg}"
            f"  \u00b7  Median: {total_s['median_days']:.1f}d"
        )

    # ── Sub-section B: 3+ days notice ─────────────────────────────────────────
    flagged_tasks = [m for m in tasks if m["gid"] in flags]
    if flagged_tasks:
        lines.append("")
        lines.append("  3+ days notice  [Last-Minute = built with <1 biz day remaining before send]:")
        for builder in ["Emmanuel", "Momina"]:
            b_flagged = [m for m in flagged_tasks if m["builder_group"] == builder]
            s = builder_week_stats(b_flagged)
            b_flag_list = [flags[m["gid"]] for m in b_flagged]
            lm_str = ""
            if b_flag_list:
                lm = sum(task_weight(m) for m in b_flagged if flags[m["gid"]]["last_minute"])
                total_w = sum(task_weight(m) for m in b_flagged)
                lm_str = (
                    f"  \u00b7  Last-Minute: {lm}/{total_w}"
                    f" ({int(lm / total_w * 100)}%)"
                )
            if s:
                lines.append(
                    f"    {builder} \u2014 {s['count']} builds"
                    f"  \u00b7  Avg: {s['avg_days']:.1f}d"
                    f"  \u00b7  Median: {s['median_days']:.1f}d{lm_str}"
                )
            else:
                lines.append(f"    {builder} \u2014 0 builds")
        total_flagged_s = builder_week_stats(flagged_tasks)
        total_lm = ""
        if flagged_tasks:
            lm = sum(task_weight(m) for m in flagged_tasks if flags[m["gid"]]["last_minute"])
            total_w = sum(task_weight(m) for m in flagged_tasks)
            total_lm = (
                f"  \u00b7  Last-Minute: {lm}/{total_w}"
                f" ({int(lm / total_w * 100)}%)"
            ) if total_w else ""
        if total_flagged_s:
            lines.append(
                f"    Total \u2014 {total_flagged_s['count']} builds"
                f"  \u00b7  Avg: {total_flagged_s['avg_days']:.1f}d"
                f"  \u00b7  Median: {total_flagged_s['median_days']:.1f}d{total_lm}"
            )

    # ── Sub-section C: Short notice ───────────────────────────────────────────
    short_tasks = [m for m in tasks if m["gid"] not in flags]

    # Compute last-minute flags for short-notice tasks that have a due date.
    # Only flag as last-minute when lead >= 1 day — if materials arrived with
    # under a day to spare the builder had no real window regardless.
    short_lm: dict[str, bool] = {}
    for m in short_tasks:
        if not m.get("ready_to_code_at") or not m.get("build_done_at"):
            continue
        deadline = task_deadline_dt(m)
        if not deadline:
            continue
        rtc_dt = datetime.fromisoformat(m["ready_to_code_at"])
        done_dt = datetime.fromisoformat(m["build_done_at"])
        lead = business_hours_between(rtc_dt, deadline) / BUSINESS_DAY_HOURS
        remaining = business_hours_between(done_dt, deadline) / BUSINESS_DAY_HOURS
        short_lm[m["gid"]] = remaining < 1.0 and lead >= 1.0

    if short_tasks:
        lines.append("")
        lines.append("  Short notice (<3 days or no due date)  [Last-Minute = <1 biz day remaining before send; only counted when builder had 1+ day lead]:")
        for builder in ["Emmanuel", "Momina"]:
            b_short = [m for m in short_tasks if m["builder_group"] == builder]
            s = builder_week_stats(b_short)
            b_lm = {gid: v for gid, v in short_lm.items() if any(m["gid"] == gid for m in b_short)}
            lm_str = ""
            if b_lm:
                lm = sum(task_weight(m) for m in b_short if short_lm.get(m["gid"]))
                total_w = sum(task_weight(m) for m in b_short if m["gid"] in short_lm)
                lm_str = f"  \u00b7  Last-Minute: {lm}/{total_w} ({int(lm / total_w * 100)}%)" if total_w else ""
            if s:
                lines.append(
                    f"    {builder} \u2014 {s['count']} builds"
                    f"  \u00b7  Avg: {s['avg_days']:.1f}d"
                    f"  \u00b7  Median: {s['median_days']:.1f}d{lm_str}"
                )
            else:
                lines.append(f"    {builder} \u2014 0 builds")
        total_short_s = builder_week_stats(short_tasks)
        total_lm_w = sum(task_weight(m) for m in short_tasks if m["gid"] in short_lm)
        total_lm_lm = sum(task_weight(m) for m in short_tasks if short_lm.get(m["gid"]))
        total_lm_str = (
            f"  \u00b7  Last-Minute: {total_lm_lm}/{total_lm_w} ({int(total_lm_lm / total_lm_w * 100)}%)"
        ) if total_lm_w else ""
        if total_short_s:
            lines.append(
                f"    Total \u2014 {total_short_s['count']} builds"
                f"  \u00b7  Avg: {total_short_s['avg_days']:.1f}d"
                f"  \u00b7  Median: {total_short_s['median_days']:.1f}d{total_lm_str}"
            )

    # ── Volume sub-sections ───────────────────────────────────────────────────
    lines.append("")
    lines.append("  BUILD VOLUME")

    # ── Sub-section D: Builds by Day (per producer) ───────────────────────────
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_abbr = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    counts: dict[str, dict[str, int]] = {
        "Emmanuel": {d: 0 for d in day_order},
        "Momina":   {d: 0 for d in day_order},
        "Total":    {d: 0 for d in day_order},
    }
    day_hours: dict[str, dict[str, list]] = {
        "Emmanuel": {d: [] for d in day_order},
        "Momina":   {d: [] for d in day_order},
        "Total":    {d: [] for d in day_order},
    }
    for m in tasks:
        weekday = datetime.fromisoformat(m["build_done_at"]).astimezone(ET).date().weekday()
        day = day_abbr.get(weekday)
        w = task_weight(m)
        if m["builder_group"] in counts:
            counts[m["builder_group"]][day] += w
            if m.get("build_hours") is not None:
                day_hours[m["builder_group"]][day].extend([m["build_hours"]] * w)
        counts["Total"][day] += w
        if m.get("build_hours") is not None:
            day_hours["Total"][day].extend([m["build_hours"]] * w)

    for builder in ["Emmanuel", "Momina", "Total"]:
        lines.append("")
        lines.append(f"  Builds by Day ({builder}):")
        for day in day_order:
            lines.append(f"    {day} \u2014 {counts[builder][day]}")
        builder_total = sum(counts[builder].values())
        fri_count = counts[builder]["Fri"]
        if builder_total > 0:
            fri_pct = int(fri_count / builder_total * 100)
            daily_avg = round(builder_total / 5, 1)
            lines.append(f"    Friday Builds: {fri_count} ({fri_pct}% of weekly output  \u00b7  {daily_avg} avg/day)")


def build_text_sms_push(all_metrics: list, last_week: tuple, prior_week: tuple) -> str:
    """Build plain-text SMS + Push section (volume and speed, same structure as email)."""
    lw_start, lw_end = last_week
    pw_start, pw_end = prior_week

    lw_tasks = week_tasks(all_metrics, lw_start, lw_end)
    pw_tasks = week_tasks(all_metrics, pw_start, pw_end)

    if not lw_tasks and not pw_tasks:
        return ""

    lines = []
    lines.append("SMS + PUSH — LAST 5 BIZ DAYS")
    lines.append("")

    # ── All builds ─────────────────────────────────────────────────────────────
    lines.append("  All builds:")
    for builder in ["Emmanuel", "Momina"]:
        b_tasks = [m for m in lw_tasks if m["builder_group"] == builder]
        s = builder_week_stats(b_tasks)
        prev_b = [m for m in pw_tasks if m["builder_group"] == builder]
        ps = builder_week_stats(prev_b)
        delta_count = _fmt_delta(s["count"], ps["count"], fmt="0g") if s and ps else ""
        delta_avg = _fmt_delta(s["avg_days"], ps["avg_days"], unit="d") if s and ps else ""
        if s:
            lines.append(
                f"    {builder} \u2014 {s['count']} built{delta_count}"
                f"  \u00b7  Avg: {s['avg_days']:.1f}d{delta_avg}"
                f"  \u00b7  Median: {s['median_days']:.1f}d"
            )
        else:
            lines.append(f"    {builder} \u2014 0 built")
    total_s = builder_week_stats(lw_tasks)
    if total_s:
        prev_total = builder_week_stats(pw_tasks)
        delta_total_count = _fmt_delta(total_s["count"], prev_total["count"], fmt="0g") if prev_total else ""
        delta_total_avg = _fmt_delta(total_s["avg_days"], prev_total["avg_days"], unit="d") if prev_total else ""
        lines.append(
            f"    Total \u2014 {total_s['count']} built{delta_total_count}"
            f"  \u00b7  Avg: {total_s['avg_days']:.1f}d{delta_total_avg}"
            f"  \u00b7  Median: {total_s['median_days']:.1f}d"
        )

    # ── Build volume by day ────────────────────────────────────────────────────
    lines.append("")
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_abbr = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    counts: dict[str, dict[str, int]] = {
        "Emmanuel": {d: 0 for d in day_order},
        "Momina":   {d: 0 for d in day_order},
        "Total":    {d: 0 for d in day_order},
    }
    for m in lw_tasks:
        if not m.get("build_done_at"):
            continue
        weekday = datetime.fromisoformat(m["build_done_at"]).astimezone(ET).date().weekday()
        day = day_abbr.get(weekday)
        w = task_weight(m)
        if m["builder_group"] in counts:
            counts[m["builder_group"]][day] += w
        counts["Total"][day] += w

    for builder in ["Emmanuel", "Momina", "Total"]:
        lines.append("")
        lines.append(f"  Builds by Day ({builder}):")
        for day in day_order:
            lines.append(f"    {day} \u2014 {counts[builder][day]}")
        builder_total = sum(counts[builder].values())
        fri_count = counts[builder]["Fri"]
        if builder_total > 0:
            fri_pct = int(fri_count / builder_total * 100)
            daily_avg = round(builder_total / 5, 1)
            lines.append(f"    Friday Builds: {fri_count} ({fri_pct}% of weekly output  \u00b7  {daily_avg} avg/day)")

    return "\n".join(lines)


def pick_color(all_metrics: list, lw_start: date, lw_end: date) -> str:
    """Choose green/yellow/red based on last week's median build time."""
    lw_tasks_all = week_tasks(all_metrics, lw_start, lw_end)
    if not lw_tasks_all:
        return "yellow"
    hours = [m["build_hours"] for m in lw_tasks_all if m.get("build_hours") is not None]
    if not hours:
        return "yellow"
    med_days = median(hours) / BUSINESS_DAY_HOURS
    if med_days <= 1.5:
        return "green"
    if med_days <= 2.5:
        return "yellow"
    return "red"


# ── Asana posting ─────────────────────────────────────────────────────────────

def post_project_status(
    token: str,
    project_gid: str,
    title: str,
    text: str,
    color: str,
) -> bool:
    """Post an Asana project status update (plain text). Returns True on success."""
    resp = requests.post(
        f"{ASANA_BASE_URL}/projects/{project_gid}/project_statuses",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"data": {
            "title": title,
            "text": text,
            "color": color,
        }},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  Asana API error {resp.status_code}: {resp.text[:400]}")
        return False
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Post weekly velocity dashboard to Asana")
    parser.add_argument("--dry-run", action="store_true", help="Print HTML, don't post")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Run --patch-due-on first to update task due dates (~30s)",
    )
    parser.add_argument("--project-gid", default=None, help="Override VELOCITY_PROJECT_GID env var")
    args = parser.parse_args()

    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    project_gid = args.project_gid or os.environ.get("VELOCITY_PROJECT_GID")
    if not project_gid and not args.dry_run:
        print(
            "Error: VELOCITY_PROJECT_GID not set.\n"
            "Create a private Asana project, add its GID to .env as VELOCITY_PROJECT_GID=<gid>,\n"
            "or pass --project-gid <gid>."
        )
        sys.exit(1)

    # Optionally refresh due dates
    if args.refresh:
        if not CACHE_FILE.exists():
            print(f"Error: No cache at {CACHE_FILE}. Run lifecycle_velocity_tracker.py --fetch first.")
            sys.exit(1)
        client = AsanaClient(token)
        print("Refreshing due dates from Asana...")
        patch_due_on(client, CACHE_FILE)

    if not CACHE_FILE.exists():
        print(f"Error: No cache at {CACHE_FILE}. Run lifecycle_velocity_tracker.py --fetch first.")
        sys.exit(1)

    print(f"Loading {CACHE_FILE}...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    print(f"  {len(data)} email task records")

    # Compute metrics (include STO tests with exclude_sto=False)
    print("Computing metrics...")
    all_metrics = []
    for entry in data:
        m = compute_task_metrics(entry, exclude_sto=False)
        if m is not None:
            all_metrics.append(m)

    complete = sum(1 for m in all_metrics if m["status"] == "complete")
    in_prog = sum(1 for m in all_metrics if m["status"] == "in_progress")
    sto_count = sum(1 for m in all_metrics if m.get("is_sto_test"))
    print(f"  Complete: {complete}, In progress: {in_prog}, STO tests included: {sto_count}")

    last_10 = get_last_n_business_days(10)
    lw_start, lw_end = last_10[5], last_10[9]   # most recent 5 completed biz days
    pw_start, pw_end = last_10[0], last_10[4]   # prior 5 completed biz days

    # Load SMS/Push metrics if cache exists
    sms_push_metrics = []
    if SMS_PUSH_CACHE_FILE.exists():
        print(f"Loading {SMS_PUSH_CACHE_FILE}...")
        with open(SMS_PUSH_CACHE_FILE) as f:
            sms_push_data = json.load(f)
        print(f"  {len(sms_push_data)} SMS/Push task records")
        for entry in sms_push_data:
            m = compute_task_metrics(entry, exclude_sto=True)
            if m is not None:
                sms_push_metrics.append(m)
    else:
        print(f"No SMS/Push cache found at {SMS_PUSH_CACHE_FILE} — run lifecycle_velocity_tracker.py --fetch-sms-push to generate")

    text = build_text(all_metrics, (lw_start, lw_end), (pw_start, pw_end))
    if sms_push_metrics:
        sms_push_text = build_text_sms_push(sms_push_metrics, (lw_start, lw_end), (pw_start, pw_end))
        if sms_push_text:
            text = text + "\n\n" + sms_push_text
    color = pick_color(all_metrics, lw_start, lw_end)
    title = f"Velocity — {lw_start.strftime('%b %d')}–{lw_end.strftime('%b %d, %Y')}"

    if args.dry_run:
        print(f"\n{'─' * 60}")
        print(f"Title: {title}  |  Color: {color}")
        print("─" * 60)
        print(text)
        print("─" * 60)
        print("(dry run — not posted to Asana)")
        return

    print(f"Posting to project {project_gid}...")
    ok = post_project_status(token, project_gid, title, text, color)
    if ok:
        print(f"  ✓ Posted: '{title}' ({color})")
    else:
        print("  ✗ Post failed — see error above")
        sys.exit(1)


if __name__ == "__main__":
    main()

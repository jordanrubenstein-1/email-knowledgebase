#!/usr/bin/env python3
"""
copy_subtask.py — Lacy Morris copy subtask + notification for SMS/Push tasks
and for the CZ/TI/STF "copy-first" email process (Awaiting Copy -> Lacy inputs
copy -> Lacy flips to Awaiting Creative herself).

CREATION is owned by the native Asana "Lacy Notification Rule" (fires on
brand ∈ {CZ, TI, SF} + Awaiting Copy, and on SMS/Push tasks). This script is a
SAFETY NET + due-date manager + Brand-field sync, not the primary creator:

  1. Synchronously during briefing — call `ensure_copy_subtask(task_gid=...)`
     (or run this file as a CLI) right after setting a qualifying task to
     "Awaiting Creative" / "Awaiting Copy". Creates the subtask only if the
     Asana rule hasn't already.
  2. As a 15-min safety net — `poll_ready_tasks.py` calls
     `poll_awaiting_creative_copy_subtasks()` on every run, so any task that
     reaches a trigger status through any path (the Asana rule, Claude, a human
     in the Asana UI) still gets its copy subtask within 15 minutes, and its
     due date re-stamped per the tiering below.

Idempotent: both paths call `ensure_copy_subtask`, which never creates a second
copy subtask if one already exists (whether created by this script or the
native Asana rule). A COMPLETED copy subtask is treated as "cycle done" and is
never recreated or touched — this is what prevents re-@mentioning Lacy for
already-approved copy (the bug that spammed CZ email tasks on 2026-07-17).

Due-date rule — the Asana rule stamps every copy subtask at "fire + 2 working
days", so a month briefed at once lands on Lacy all the same day (and a flat
"weeks-out" tier system still bunches every far-out send onto one date — a
whole Labor Day Event's worth of copy subtasks all landed on the same Tuesday
before this was fixed, confirmed 2026-07-22). The poller instead re-stamps each
copy subtask to exactly 2 weeks before its parent send date, pulled back to the
preceding Friday if that lands on a weekend (never pushed forward into the
following week). If 2-weeks-before would be earlier than the rule's own
fire+2 near-term turnaround, there's no real runway to give, so that near-term
date is left standing instead. See _copy_due_for. This also self-heals when a
parent send date moves.

For each qualifying task it:
  - Creates (only if missing) a subtask "[task name] Copy" assigned to Lacy
    Morris, due per the rule above (never on a weekend).
  - Copies the parent's Brand custom field onto the subtask.
  - Posts a comment on the parent @-mentioning Lacy that the brief is ready.
  - On every poll (not just at creation), re-syncs the subtask's Brand field
    to match its parent's current Brand value — including clearing it if the
    parent has no Brand set. This is what makes it safe to remove any
    fixed-value "set Brand" action from the native Asana rule itself: Asana
    rule actions can only write a constant, not "copy the parent's field," so
    a rule authored/extended for one brand (e.g. it was written for CZ, then
    the trigger condition was broadened to TI/STF/BUR/HAV without updating
    this action) silently stamps every new copy subtask with that one fixed
    brand regardless of the parent's real brand — confirmed root cause of the
    117-task CZ mislabeling found/fixed 2026-08-11
    (memory/project_cz_ti_bur_brand_mislabel.md). Since the rule can't express
    "copy from parent" as an action, the fix is to drop that action from the
    rule entirely and let this poller (already running every 15 min via the
    `com.havenly.poll-ready-tasks` LaunchAgent) own Brand sync going forward.

Eligible tasks: Channel SMS or Push (any brand), OR a copy-first brand
(CZ / TI / STF / BUR / HAV, any channel — matching the native Asana rule's brand set).
EXCLUDED regardless of brand/channel: Type = Banner/Module tasks (creative
request tickets for promo banners / Havenly popups — they carry no copy), and
any task with "email footer" or "footer refresh" in its title (case-insensitive
— quarterly footer imagery refreshes, not a copy request).

Usage (synchronous / manual):
    uv run python scripts/braze_automation/copy_subtask.py --task-gid GID [--dry-run]
    uv run python scripts/braze_automation/copy_subtask.py --poll [--dry-run]
"""

import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Reuse the Asana request layer + parsing helpers already used across the
# braze_automation package so behavior (auth, 429 retry, field access) matches.
from build_sms_campaign import (
    _asana_request,
    fetch_task_by_gid,
    _get_enum_value_gid,
    _get_enum_value_name,
    ASANA_PROJECT_GID,
    ASANA_WORKSPACE_GID,
    FIELD_TASK_STATUS,
    FIELD_CHANNEL,
    FIELD_BRAND,
    CHANNEL_OPTIONS,
    BRAND_OPTIONS,
)

logger = logging.getLogger(__name__)

# --- Constants ------------------------------------------------------------

LACY_GID = "1212463876283471"  # Lacy Morris (Asana user)
STATUS_AWAITING_CREATIVE = "1209982215610994"
STATUS_AWAITING_COPY = "1213916481930051"

# "Type" custom field + the Banner/Module option. Banner/Module tasks are
# creative-request tickets (email-drip promo banners, Havenly popups) with NO
# copy to write, so they must never get a Lacy copy subtask even when their
# brand is a copy-first brand (CZ/TI/STF) at Awaiting Creative — see the gate in
# ensure_copy_subtask.
FIELD_TYPE = "1207522425689987"
TYPE_BANNER_MODULE = "1209982215611001"
CHANNEL_SMS = CHANNEL_OPTIONS["sms"]
CHANNEL_PUSH = CHANNEL_OPTIONS["push"]
_ELIGIBLE_CHANNELS = {CHANNEL_SMS, CHANNEL_PUSH}

# Quarterly "footer refresh" tasks (e.g. "Fall Email Footer Refresh") are an
# imagery swap, not a copy request — no Type/Category value distinguishes them,
# so exclude by title. Matches "email footer" or "footer refresh" anywhere in
# the name, case-insensitive (confirmed friction on GID 1213317185744565: Lacy
# was tagged in with nothing to write).
_FOOTER_REFRESH_TITLE_MARKERS = ("email footer", "footer refresh")


def _is_footer_refresh_title(name: str) -> bool:
    lowered = (name or "").lower()
    return any(marker in lowered for marker in _FOOTER_REFRESH_TITLE_MARKERS)

# Brands whose EMAIL tasks run the copy-first process (task set to Awaiting Copy
# during briefing → the native Asana "Lacy Notification Rule" fires on brand ∈
# {CZ, TI, SF, BUR, HAV} + Awaiting Copy and creates the copy subtask). We keep
# this set in lockstep with that Asana rule so the poller can act as a safety
# net for the same brands. (SMS/Push of ANY brand are also eligible — see the
# gate below.) HAV was added 2026-07-29 — briefing-only switch (auto-build still
# uses the existing DnD-duplicator path, not the HTML/CSS builder); like BUR
# before it, the native Asana rule's own brand condition still needs HAV added
# manually in Asana's rule builder (Workflow > Rules) for the primary/instant
# trigger to fire — until that manual step is done, HAV's copy subtasks are
# created only by the 15-min poller safety net, not instantly.
BRAND_CZ = BRAND_OPTIONS["CZ"]
BRAND_TI = BRAND_OPTIONS["TI"]
BRAND_STF = BRAND_OPTIONS["STF"]
BRAND_BUR = BRAND_OPTIONS["BUR"]
BRAND_HAV = BRAND_OPTIONS["HAV"]
_COPY_FIRST_BRANDS = {BRAND_CZ, BRAND_TI, BRAND_STF, BRAND_BUR, BRAND_HAV}

# Either status triggers the copy subtask. (CZ/STF/TI route to Awaiting Copy;
# SMS/Push of other brands go to Awaiting Creative — both fire.)
_TRIGGER_STATUSES = (STATUS_AWAITING_CREATIVE, STATUS_AWAITING_COPY)

# --- Copy-subtask due-date rule -------------------------------------------
#
# The native Asana rule stamps every copy subtask at "fire date + 2 working
# days". When a whole month is briefed at once that dumps a month of copy on
# Lacy all due the same day — and a flat "N weeks out" tier system still
# bunches every far-out send onto one date (a whole Labor Day Event's worth of
# sends all landed on the same Tuesday before this was fixed, confirmed
# 2026-07-22).
#
# The rule: copy is due exactly 4 weeks (28 calendar days) before the send
# date (changed from 2 weeks on 2026-07-22 per team request — Lacy wants more
# lead time). If that lands on a Saturday or Sunday, pull it back to the
# preceding Friday (never push forward into the following week — Lacy should
# have the copy done well before the send, not right up against it). Example:
# send Sunday 8/23 -> 8/23 - 28d = Sunday 7/26 -> pulled back to Friday 7/24.
#
# Near-term guard: if that 4-weeks-before date would fall before the near-term
# default (today/brief date + 2 working days — the native Asana rule's own
# turnaround), there isn't a real 4 weeks of runway to give, so the rule's
# near-term date is left standing untouched instead. When a whole early batch
# of sends all fall into this near-term bucket at once (e.g. a month briefed
# today where the first 1-2 weeks of sends are all too soon for a full 4-week
# lead), that's a one-time manual spread, not something this formula handles —
# see the 2026-07-22 STF Aug batch for an example of hand-spreading those
# across a few near-term days instead of dumping them all on one date.
_COPY_LEAD_DAYS = 28
_LEAD_NEAR_TERM = 2  # matches the Asana rule's fire+2 (used only on create, and as the near-term floor)

# --- Safety-net guards ----------------------------------------------------
#
# The poller CREATES a copy subtask only as a safety net for a genuine RECENT
# miss (the native Asana rule failed to create one for a just-briefed task). It
# must NOT mass-create for a whole existing backlog — doing so tags Lacy on
# dozens of tasks at once (this is exactly what happened to the TI/STF backlog
# on 2026-07-18 when the poller ran mid-edit). So creation requires BOTH:
#   - the parent task was created within the last N days (a recent brief), and
#   - the parent's send date has not already passed.
_SAFETY_NET_CREATE_MAX_AGE_DAYS = 4

# Due-date re-stamping (the tiering above) is applied ONLY going forward — to
# copy subtasks created on or after this cutoff. The existing backlog keeps
# whatever due date it already has, so the poller never mass-shifts historical
# dates. Set to the day after the tiering was introduced.
_RESTAMP_CREATED_ON_OR_AFTER = "2026-07-19"


def _days_between(earlier: str, later: str) -> Optional[int]:
    """Whole days from `earlier` to `later` (both YYYY-MM-DD); None if unparsable."""
    try:
        return (datetime.strptime(later, "%Y-%m-%d") - datetime.strptime(earlier, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def _due_date_working_days_after(anchor: str, n: int) -> Optional[str]:
    """Return the date `n` working days AFTER `anchor` (YYYY-MM-DD).

    Weekends are not counted and the result never lands on a weekend (we only
    increment the counter on weekdays). Example (n=2): brief Thursday -> next
    Monday (Thu->Fri->Mon).
    """
    try:
        current = datetime.strptime(anchor, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    counted = 0
    while counted < n:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            counted += 1
    return current.strftime("%Y-%m-%d")


def _copy_due_for(parent_due: Optional[str], anchor: str) -> tuple:
    """Compute the copy subtask's due date: exactly 2 weeks before the send,
    pulled back to the preceding Friday if that lands on a weekend.

    Returns (due_str_or_None, is_far_tier). `is_far_tier` is True only when the
    2-weeks-before date is actually used (i.e. it falls at or after the
    near-term floor); near-term sends — where 2 weeks before send is earlier
    than the rule's own fire+2 turnaround — return is_far_tier=False so the
    caller leaves the rule's near-term date untouched instead.
    """
    near_term_default = _due_date_working_days_after(anchor, _LEAD_NEAR_TERM)
    if not parent_due:
        return near_term_default, False
    try:
        send_dt = datetime.strptime(parent_due, "%Y-%m-%d")
    except (TypeError, ValueError):
        return near_term_default, False
    target_dt = send_dt - timedelta(days=_COPY_LEAD_DAYS)
    if target_dt.weekday() == 5:  # Saturday -> preceding Friday
        target_dt -= timedelta(days=1)
    elif target_dt.weekday() == 6:  # Sunday -> preceding Friday
        target_dt -= timedelta(days=2)
    target_str = target_dt.strftime("%Y-%m-%d")
    if near_term_default and target_str < near_term_default:
        # Less than a real 2 weeks of runway from the brief date — no room to
        # push the date out further, so leave the rule's near-term date alone.
        return near_term_default, False
    return target_str, True


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# --- Idempotency ----------------------------------------------------------

def _find_existing_copy_subtask(parent_gid: str, parent_name: str) -> Optional[Dict]:
    """Return the parent's copy subtask dict, if any — completed OR incomplete.

    Treats a subtask as the copy subtask if it is named "<parent> Copy", or if
    it is assigned to Lacy with "copy" in the name — covers both this script and
    any copy subtask created by the native Asana rule (whose enabled/paused
    state should NOT be assumed — see memory/project_lacy_notification_rule_still_active.md),
    so we never duplicate.

    A COMPLETED copy subtask is honored too, and wins over an incomplete one: if
    the copy cycle already ran to completion (Lacy wrote the copy, it was
    approved), recreating a fresh copy subtask re-@mentions Lacy for work that's
    already done — exactly the false-notification bug that hit CZ email tasks
    after they became eligible for the copy subtask. The caller uses the
    `completed` flag to skip cleanly rather than syncing a due date onto a
    finished subtask.
    """
    subtasks = _asana_request(
        "GET",
        f"tasks/{parent_gid}/subtasks",
        params={
            "opt_fields": (
                "name,completed,assignee.gid,due_on,created_at,"
                "custom_fields,custom_fields.gid,"
                "custom_fields.enum_value,custom_fields.enum_value.gid,"
                "custom_fields.enum_value.name"
            )
        },
    )
    if not subtasks:
        return None
    target = f"{parent_name.strip().lower()} copy"
    incomplete_match: Optional[Dict] = None
    for st in subtasks:
        name = (st.get("name") or "").strip().lower()
        if not name:
            continue
        is_match = name == target
        if not is_match:
            assignee = (st.get("assignee") or {}).get("gid")
            is_match = assignee == LACY_GID and "copy" in name
        if not is_match:
            continue
        if st.get("completed"):
            return st  # completed cycle wins — never recreate/re-notify
        if incomplete_match is None:
            incomplete_match = st
    return incomplete_match


# --- Core -----------------------------------------------------------------

def ensure_copy_subtask(
    task: Optional[Dict] = None,
    task_gid: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """Ensure the Lacy copy subtask + notification exist for one task.

    Pass either a pre-fetched `task` dict (with custom_fields, name, due_on) or a
    `task_gid` to fetch. Returns a result dict: {status, reason, subtask_gid?}.
    status is one of: created | synced | skipped | dry_run | error.
    """
    if task is None:
        if not task_gid:
            return {"status": "error", "reason": "no task or task_gid provided"}
        task = fetch_task_by_gid(task_gid)
    if not task:
        return {"status": "error", "reason": "task not found"}

    gid = task.get("gid") or task_gid
    name = (task.get("name") or "").strip()

    # Banner/Module creative-request tickets (email-drip promo banners, Havenly
    # popups) carry no copy — exclude them outright, even for a copy-first brand
    # (CZ/TI/STF) at Awaiting Creative, so the poller never tags Lacy on them.
    if _get_enum_value_gid(task, FIELD_TYPE) == TYPE_BANNER_MODULE:
        return {"status": "skipped", "reason": "Banner/Module creative request — no copy subtask"}

    # Quarterly footer refresh tasks are an imagery swap, not a copy request —
    # exclude by title regardless of brand/channel (see marker comment above).
    if _is_footer_refresh_title(name):
        return {"status": "skipped", "reason": "footer refresh task — no copy subtask"}

    # Gate: eligible if SMS/Push (any brand) OR a copy-first brand (CZ/TI/STF,
    # any channel), at a copy-brief-ready status — Awaiting Creative or Copy.
    channel_gid = _get_enum_value_gid(task, FIELD_CHANNEL)
    brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
    if channel_gid not in _ELIGIBLE_CHANNELS and brand_gid not in _COPY_FIRST_BRANDS:
        return {"status": "skipped", "reason": f"not SMS/Push and not a copy-first brand ({_get_enum_value_name(task, FIELD_BRAND)})"}
    status_gid = _get_enum_value_gid(task, FIELD_TASK_STATUS)
    if status_gid not in _TRIGGER_STATUSES:
        return {"status": "skipped", "reason": f"status not Awaiting Creative/Copy ({_get_enum_value_name(task, FIELD_TASK_STATUS)})"}

    due_on = task.get("due_on")

    # The native Asana rule owns CREATION for CZ/TI/STF; this helper is a safety
    # net (creates only if the rule missed one) AND re-stamps the due date on
    # far-out sends so a whole month briefed at once doesn't all land on Lacy
    # the same day (see _copy_due_for). Due dates are anchored to the brief/fire
    # date so they stay stable across polls.
    existing = _find_existing_copy_subtask(gid, name)
    if existing:
        # A completed copy subtask means the copy cycle already ran to
        # completion — do NOT recreate or touch it (would re-@mention Lacy for
        # already-approved copy). Skip cleanly.
        if existing.get("completed"):
            return {"status": "skipped", "reason": "copy subtask already completed", "subtask_gid": existing.get("gid")}
        # Anchor tier math to when the subtask was briefed/created so the due
        # date is stable across polls. Only the >3wk / >4wk tiers are actively
        # managed — near-term sends keep the rule's fire+2 date untouched — and
        # only for subtasks created on/after the going-forward cutoff, so the
        # existing backlog's dates are never mass-shifted.
        anchor = (existing.get("created_at") or "")[:10] or _today_str()
        expected_due, is_far = _copy_due_for(due_on, anchor)
        existing_due = existing.get("due_on")
        due_needs_sync = (
            is_far
            and anchor >= _RESTAMP_CREATED_ON_OR_AFTER
            and expected_due
            and existing_due != expected_due
        )

        # Brand sync — runs on every poll, regardless of the due-date tier
        # above. `brand_gid` (the parent's current Brand, or None if the
        # parent has no Brand set) was already resolved earlier in this
        # function. This is what corrects a subtask stamped with a fixed
        # brand value by the native Asana rule's own action (see module
        # docstring) — including clearing the field when the parent has no
        # Brand at all, not just remapping it to a different one.
        existing_brand_gid = _get_enum_value_gid(existing, FIELD_BRAND)
        brand_needs_sync = existing_brand_gid != brand_gid

        if not due_needs_sync and not brand_needs_sync:
            return {"status": "skipped", "reason": "copy subtask already exists and in sync"}

        if dry_run:
            reason_parts = []
            if due_needs_sync:
                reason_parts.append("due date")
            if brand_needs_sync:
                reason_parts.append("Brand field")
            return {
                "status": "dry_run",
                "reason": f"would sync: {', '.join(reason_parts)}",
                "subtask_gid": existing.get("gid"),
                **({"old_due": existing_due, "new_due": expected_due} if due_needs_sync else {}),
                **({"old_brand_gid": existing_brand_gid, "new_brand_gid": brand_gid} if brand_needs_sync else {}),
            }

        update_data: Dict = {}
        if due_needs_sync:
            update_data["due_on"] = expected_due
        if brand_needs_sync:
            # Asana clears an enum custom field when its value is set to None.
            update_data["custom_fields"] = {FIELD_BRAND: brand_gid}

        updated = _asana_request(
            "PUT", f"tasks/{existing['gid']}", json_data={"data": update_data}
        )
        if updated is None:
            return {"status": "error", "reason": "sync failed", "subtask_gid": existing.get("gid")}
        return {
            "status": "synced",
            "subtask_gid": existing.get("gid"),
            **({"old_due": existing_due, "new_due": expected_due} if due_needs_sync else {}),
            **({"old_brand_gid": existing_brand_gid, "new_brand_gid": brand_gid} if brand_needs_sync else {}),
        }

    # No existing subtask — safety-net create, but ONLY for a genuine recent
    # miss. Skip if the send date has already passed, and skip backlog tasks
    # (briefed more than N days ago) so we never mass-create for an existing
    # backlog and tag Lacy on dozens of tasks at once.
    today = _today_str()
    if due_on and due_on < today:
        return {"status": "skipped", "reason": f"due date already passed ({due_on})"}
    created_at = (task.get("created_at") or "")[:10]
    if not created_at:
        # The task dict didn't carry created_at (synchronous path) — fetch it.
        full = _asana_request("GET", f"tasks/{gid}", params={"opt_fields": "created_at"})
        created_at = ((full or {}).get("created_at") or "")[:10]
    age = _days_between(created_at, today) if created_at else None
    if age is None or age > _SAFETY_NET_CREATE_MAX_AGE_DAYS:
        return {
            "status": "skipped",
            "reason": (
                f"backlog task (created {created_at or '?'}, "
                f">{_SAFETY_NET_CREATE_MAX_AGE_DAYS}d ago) — safety net only backs up recent misses"
            ),
        }
    subtask_due, _ = _copy_due_for(due_on, today)

    if dry_run:
        return {
            "status": "dry_run",
            "reason": "would create copy subtask + comment",
            "subtask_name": f"{name} Copy",
            "subtask_due": subtask_due,
            "brand_gid": brand_gid,
        }

    # Create the subtask.
    subtask_payload: Dict = {
        "name": f"{name} Copy",
        "assignee": LACY_GID,
    }
    if subtask_due:
        subtask_payload["due_on"] = subtask_due
    if brand_gid:
        subtask_payload["custom_fields"] = {FIELD_BRAND: brand_gid}

    created = _asana_request(
        "POST", f"tasks/{gid}/subtasks", json_data={"data": subtask_payload}
    )
    if not created:
        return {"status": "error", "reason": "subtask creation failed"}
    subtask_gid = created.get("gid")

    # Post the notification comment @-mentioning Lacy (href must be non-empty).
    comment_html = (
        f'<body>Hi <a data-asana-type="user" data-asana-gid="{LACY_GID}" '
        f'href="https://app.asana.com/0/{LACY_GID}">@Lacy Morris</a>, '
        f"the brief for {name} is ready for you!</body>"
    )
    comment_ok = _asana_request(
        "POST",
        f"tasks/{gid}/stories",
        json_data={"data": {"html_text": comment_html, "is_pinned": False}},
    )

    return {
        "status": "created",
        "subtask_gid": subtask_gid,
        "subtask_due": subtask_due,
        "comment_posted": bool(comment_ok),
    }


# --- Poller entrypoint ----------------------------------------------------

_SEARCH_OPT_FIELDS = ",".join([
    "name", "due_on", "completed", "created_at",
    "custom_fields", "custom_fields.gid",
    "custom_fields.enum_value", "custom_fields.enum_value.gid",
    "custom_fields.enum_value.name",
])


def _fetch_trigger_tasks(status_gid: str, channel_gid: Optional[str] = None, brand_gid: Optional[str] = None) -> List[Dict]:
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": status_gid,
        "opt_fields": _SEARCH_OPT_FIELDS,
        "limit": 100,
    }
    if channel_gid:
        params[f"custom_fields.{FIELD_CHANNEL}.value"] = channel_gid
    if brand_gid:
        params[f"custom_fields.{FIELD_BRAND}.value"] = brand_gid
    data = _asana_request(
        "GET", f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search", params=params
    )
    return [t for t in (data or []) if not t.get("completed")]


def poll_awaiting_creative_copy_subtasks(dry_run: bool = False) -> Dict:
    """Ensure the copy subtask for every eligible task at a trigger status.

    Scans both Awaiting Creative and Awaiting Copy for SMS/Push (any brand) and
    for each copy-first brand (CZ/TI/STF, any channel). Idempotent per task —
    safe to run repeatedly (the 15-min poller does). Returns a summary dict of
    counts.
    """
    summary = {"created": 0, "synced": 0, "skipped": 0, "error": 0, "dry_run": 0}
    seen = set()
    searches = (
        [(status_gid, {"channel_gid": c}) for c in (CHANNEL_SMS, CHANNEL_PUSH) for status_gid in _TRIGGER_STATUSES]
        + [(status_gid, {"brand_gid": b}) for b in _COPY_FIRST_BRANDS for status_gid in _TRIGGER_STATUSES]
    )
    for status_gid, filter_kwargs in searches:
        for task in _fetch_trigger_tasks(status_gid, **filter_kwargs):
            gid = task.get("gid")
            if not gid or gid in seen:
                continue
            seen.add(gid)
            try:
                result = ensure_copy_subtask(task=task, dry_run=dry_run)
            except Exception:
                logger.exception(f"[CopySubtask] Error on {gid}")
                summary["error"] += 1
                continue
            status = result.get("status", "error")
            summary[status] = summary.get(status, 0) + 1
            if status in ("created", "dry_run"):
                logger.info(
                    f"[CopySubtask] {status}: {task.get('name', gid)} ({gid}) "
                    f"-> due {result.get('subtask_due')}"
                )
    return summary


# --- CLI ------------------------------------------------------------------

def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Create Lacy copy subtasks for SMS/Push Awaiting Creative tasks")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-gid", help="Ensure the copy subtask for a single task GID")
    group.add_argument("--poll", action="store_true", help="Scan all SMS/Push Awaiting Creative tasks")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing to Asana")
    args = parser.parse_args()

    if args.poll:
        summary = poll_awaiting_creative_copy_subtasks(dry_run=args.dry_run)
        print(f"Copy subtask poll complete: {summary}")
    else:
        result = ensure_copy_subtask(task_gid=args.task_gid, dry_run=args.dry_run)
        print(result)


if __name__ == "__main__":
    _main()

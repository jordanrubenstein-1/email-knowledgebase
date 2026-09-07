"""
Core detection logic for Braze event/canvas volume anomaly alerts.

Deliberately decoupled from Slack/Asana/state-file concerns so it's testable
in isolation — see scripts/braze_automation/monitor_braze_anomalies.py for
the orchestrator that wires this to config, dedup state, and Slack.
"""

import re
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Callable, Optional

from utils.braze_datashare import get_app_group_id, qualified_view


# ---------------------------------------------------------------------------
# Freshness gate
# ---------------------------------------------------------------------------

def check_freshness(
    client,
    view: str,
    brand: str,
    skip_hours: float = 36,
    stale_hours: float = 72,
) -> dict:
    """Check how recently `view` has landed data for `brand`.

    Returns a dict with `status` one of:
      - "fresh":   age <= skip_hours       -> safe to evaluate normally
      - "lagging": skip_hours < age <= stale_hours -> ordinary daily lag,
                    skip evaluation silently (not an anomaly signal)
      - "stale":   age > stale_hours       -> datashare itself may be broken,
                    worth a distinct low-urgency warning
      - "no_data": no rows at all for this brand/view (likely misconfigured
                    APP_GROUP_ID or a brand-new view)
    """
    table = qualified_view(view, brand)
    app_group_id = get_app_group_id(brand)
    rows = client.execute_query(
        f"SELECT MAX(SF_CREATED_AT) AS latest FROM {table} WHERE APP_GROUP_ID = %(app_group_id)s",
        {"app_group_id": app_group_id},
    )
    latest = rows[0]["LATEST"] if rows else None
    if latest is None:
        return {"status": "no_data", "latest": None, "age_hours": None}

    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600

    if age_hours <= skip_hours:
        status = "fresh"
    elif age_hours <= stale_hours:
        status = "lagging"
    else:
        status = "stale"
    return {"status": status, "latest": latest, "age_hours": age_hours}


# ---------------------------------------------------------------------------
# Daily volume series
# ---------------------------------------------------------------------------

def get_daily_counts(
    client,
    view: str,
    brand: str,
    extra_filter_sql: str = "",
    extra_params: Optional[dict] = None,
    weeks: int = 5,
    distinct_col: str = "USER_ID",
) -> list[dict]:
    """Day-bucketed COUNT(DISTINCT distinct_col) over the trailing `weeks`
    weeks, for `brand` in `view`. Uses an integer-epoch TIME comparison
    (not TO_TIMESTAMP(TIME) >= ...) for micro-partition pruning, per the
    pattern already documented in generate_lifecycle_report.py.

    Returns a list of {"day": date, "cnt": int}, sorted ascending by day,
    EXCLUDING the current UTC calendar day. That day is always a partial
    count (whatever fraction of it has landed so far) — including it would
    silently drag down the "recent window" average and manufacture a false
    drop on every single run, since "today" always looks like a crash
    relative to a full day's normal volume. Missing days simply don't
    appear (caller should treat absence as 0 only where that's meaningful —
    evaluate_series does this for the recent window).
    """
    table = qualified_view(view, brand)
    app_group_id = get_app_group_id(brand)
    cutoff_epoch = int((datetime.now(timezone.utc) - timedelta(weeks=weeks)).timestamp())

    params = {"app_group_id": app_group_id, "cutoff_epoch": cutoff_epoch}
    if extra_params:
        params.update(extra_params)

    query = f"""
        SELECT TO_DATE(TO_TIMESTAMP(TIME)) AS day, COUNT(DISTINCT {distinct_col}) AS cnt
        FROM {table}
        WHERE APP_GROUP_ID = %(app_group_id)s
          AND TIME >= %(cutoff_epoch)s
          {extra_filter_sql}
        GROUP BY 1
        ORDER BY 1
    """
    rows = client.execute_query(query, params)
    today = datetime.now(timezone.utc).date()
    return [{"day": r["DAY"], "cnt": r["CNT"]} for r in rows if r["DAY"] < today]


# ---------------------------------------------------------------------------
# Canvas first-email-step resolution (dynamic — no static step names)
# ---------------------------------------------------------------------------

def resolve_canvas_id(canvas_name: str, brand: str) -> Optional[str]:
    """Look up a canvas's id by exact (case-insensitive) name match."""
    from braze_api_client import get_all_canvases

    for canvas in get_all_canvases(brand=brand):
        if canvas.get("name", "").strip().lower() == canvas_name.strip().lower():
            return canvas["id"]
    return None


_T_NUMBER_RE = re.compile(r"[_\s]T(\d+)[_\s]", re.IGNORECASE)


def resolve_first_email_step(canvas_id: str, brand: str) -> Optional[str]:
    """Return the step `name` of the earliest email step in the canvas, or
    None if no email step is found.

    canvas/details' `steps` array is NOT reliably in chronological/flow
    order for canvases with branches (audience_paths, experiment_paths,
    etc.) — confirmed against a real ID canvas where array order picked a
    "T9" step as if it were first. Message names in this org follow a
    `..._T<n>_...` sequence-position convention (the same one documented
    for `sequence_position` in the campaign YAML schema), so that's the
    primary signal: pick the email step with the lowest T-number. Only
    fall back to raw array order when no step carries a T-number.

    Resolved fresh on every run rather than cached/hardcoded, so step
    renames/reordering never require a config update. Still imperfect for
    canvases that don't follow the T-number convention and are also
    branched — use the `first_email_step_override` config field for those.
    """
    from braze_api_client import get_canvas_details

    details = get_canvas_details(canvas_id, brand=brand)
    if not details:
        return None

    email_steps = []  # (t_number_or_None, array_index, step_name)
    for idx, step in enumerate(details.get("steps", [])):
        messages = step.get("messages", {})
        if not isinstance(messages, dict):
            continue
        if not any((m or {}).get("channel") == "email" for m in messages.values()):
            continue
        name = step.get("name") or ""
        match = _T_NUMBER_RE.search(f"_{name}_")
        t_number = int(match.group(1)) if match else None
        email_steps.append((t_number, idx, name))

    if not email_steps:
        return None

    with_t = [s for s in email_steps if s[0] is not None]
    if with_t:
        with_t.sort(key=lambda s: (s[0], s[1]))
        return with_t[0][2]

    email_steps.sort(key=lambda s: s[1])
    return email_steps[0][2]


# ---------------------------------------------------------------------------
# Anomaly evaluation
# ---------------------------------------------------------------------------

def evaluate_series(
    daily_counts: list[dict],
    is_during_sale_fn: Callable[[object], bool],
    recent_window_days: int = 2,
    baseline_weeks: int = 4,
    drop_threshold_pct: float = 50,
) -> dict:
    """Evaluate a day-bucketed count series for a volume anomaly.

    `is_during_sale_fn` takes a `date` and returns whether that day falls
    inside an active sale for the relevant brand/audience — callers bind
    brand/havenly_audience via a closure so this function stays
    domain-agnostic.

    Two tiers:
      - Tier 1 (always active): the recent window is a hard zero while the
        baseline is non-trivial. A genuine break shows zero regardless of
        sale status, so this is never suppressed.
      - Tier 2 (non-sale days only): recent average is below
        `drop_threshold_pct`% of the non-sale trailing baseline. Skipped
        when the recent window overlaps a sale — elevated variance during
        a sale is expected, not the failure mode being guarded against.

    Returns a dict with `status` one of "no_data", "zero", "drop", "ok".
    """
    if not daily_counts:
        return {"status": "no_data"}

    series = sorted(daily_counts, key=lambda r: r["day"])
    recent = series[-recent_window_days:]
    history = series[:-recent_window_days] if len(series) > recent_window_days else []

    baseline_cutoff = recent[0]["day"] - timedelta(weeks=baseline_weeks)
    baseline_pool = [r for r in history if r["day"] >= baseline_cutoff]
    non_sale_baseline = [r for r in baseline_pool if not is_during_sale_fn(r["day"])]
    # Fall back to the full pool only if every historical day was a sale day
    # (rare) — better a sale-inflated baseline than none at all.
    baseline_source = non_sale_baseline or baseline_pool

    baseline_avg = mean(r["cnt"] for r in baseline_source) if baseline_source else None
    recent_avg = mean(r["cnt"] for r in recent)
    recent_total = sum(r["cnt"] for r in recent)
    recent_in_sale = any(is_during_sale_fn(r["day"]) for r in recent)

    result = {
        "baseline_avg": baseline_avg,
        "recent_avg": recent_avg,
        "recent_in_sale": recent_in_sale,
        "baseline_days_used": len(baseline_source),
    }

    if recent_total == 0 and baseline_avg is not None and baseline_avg >= 1:
        result["status"] = "zero"
        return result

    if not recent_in_sale and baseline_avg:
        pct_of_baseline = 100 * recent_avg / baseline_avg
        result["pct_of_baseline"] = pct_of_baseline
        if pct_of_baseline < drop_threshold_pct:
            result["status"] = "drop"
            return result

    result["status"] = "ok"
    return result

#!/usr/bin/env python3
"""
monitor_braze_anomalies.py — Slack alert when a configured Braze custom
event or lifecycle canvas's first-email-step volume drops well below its
4-week trailing baseline (excluding sale days), or stops firing entirely.

Runs once daily via LaunchAgent (com.havenly.monitor-braze-anomalies), after
the Braze Raw Events Datashare has typically caught up on the prior day.
Idempotent — dedups on "{brand}|{kind}|{name}" per calendar day (data/
braze_anomaly_state.yaml), so re-running the same day never double-posts.

Watch-lists live in data/braze_anomaly_config.yaml — see that file's header
for the schema and how to add new events/canvases per brand.

Usage:
    uv run python scripts/braze_automation/monitor_braze_anomalies.py [--dry-run] [--brand ID]
"""
import argparse
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from snowflake_client import get_snowflake_client
from utils.braze_datashare import DB_PRIMARY, SCHEMA_PRIMARY
from utils.sale_matcher import load_sale_schedules, is_during_sale
from utils.slack_client import post_message
from utils.anomaly_detector import (
    check_freshness,
    get_daily_counts,
    resolve_canvas_id,
    resolve_first_email_step,
    evaluate_series,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = PROJECT_ROOT / "data" / "braze_anomaly_config.yaml"
STATE_FILE = PROJECT_ROOT / "data" / "braze_anomaly_state.yaml"

EVENT_VIEW = "USERS_BEHAVIORS_CUSTOMEVENT_SHARED"
PURCHASE_VIEW = "USERS_BEHAVIORS_PURCHASE_SHARED"
EMAIL_SEND_VIEW = "USERS_MESSAGES_EMAIL_SEND_SHARED"

DEFAULT_THRESHOLDS = {
    "drop_threshold_pct": 50,
    "freshness_skip_hours": 36,
    "freshness_stale_hours": 72,
    "recent_window_days": 2,
    "baseline_weeks": 4,
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_alert_date": {}}
    with open(STATE_FILE) as f:
        return yaml.safe_load(f) or {"last_alert_date": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def _already_alerted_today(state: dict, key: str, today_str: str) -> bool:
    return state.get("last_alert_date", {}).get(key) == today_str


def _mark_alerted(state: dict, key: str, today_str: str) -> None:
    state.setdefault("last_alert_date", {})[key] = today_str


def _sale_check_fn(brand: str, sale_schedules: list, havenly_audience: Optional[str]):
    def fn(day) -> bool:
        return is_during_sale(day.isoformat(), brand, sale_schedules, havenly_audience=havenly_audience)
    return fn


def _format_alert(kind: str, name: str, brand: str, result: dict, freshness: dict) -> str:
    age_note = (
        f"Datashare last updated {freshness['age_hours']:.0f}h ago."
        if freshness.get("age_hours") is not None else ""
    )
    sale_note = "Currently in an active sale." if result.get("recent_in_sale") else "Not sale-related."
    label = "first email step" if kind == "canvas_first_email" else "event"

    if result["status"] == "zero":
        baseline = result.get("baseline_avg")
        baseline_note = f" (baseline ~{baseline:.0f}/day)" if baseline else ""
        return (
            f":rotating_light: Braze anomaly — *{name}* ({label}, {brand})\n"
            f"No sends/events in the last 2 days{baseline_note}. {sale_note} {age_note}"
        )

    pct = result.get("pct_of_baseline")
    baseline = result.get("baseline_avg")
    recent = result.get("recent_avg")
    return (
        f":rotating_light: Braze anomaly — *{name}* ({label}, {brand})\n"
        f"Last 2 days avg: {recent:.0f}/day — {pct:.0f}% of the 4-week trailing baseline ({baseline:.0f}/day)\n"
        f"{sale_note} {age_note}"
    )


def _format_stale_warning(kind: str, name: str, brand: str, freshness: dict) -> str:
    return (
        f":warning: Braze datashare may be stale for *{brand}* — skipping anomaly check for "
        f"{name} ({kind}). Last data landed {freshness['age_hours']:.0f}h ago (expected within ~36h)."
    )


def _handle_freshness_and_alert(
    brand, kind, name, key, freshness, defaults, sale_schedules,
    havenly_audience, state, today_str, dry_run, query_fn,
) -> dict:
    if freshness["status"] == "no_data":
        logger.info(f"[{brand}] {name}: no data at all — skipping")
        return {"status": "no_data"}

    if freshness["status"] == "stale":
        stale_key = f"{key}|stale"
        if _already_alerted_today(state, stale_key, today_str):
            logger.info(f"[{brand}] {name}: stale warning already sent today")
        else:
            text = _format_stale_warning(kind, name, brand, freshness)
            if dry_run:
                logger.info(f"[DRY RUN] Would post: {text}")
            elif post_message(text):
                _mark_alerted(state, stale_key, today_str)
        return {"status": "stale"}

    if freshness["status"] == "lagging":
        logger.info(f"[{brand}] {name}: datashare lagging ({freshness['age_hours']:.0f}h) — skipping this run")
        return {"status": "lagging"}

    daily_counts = query_fn()
    sale_fn = _sale_check_fn(brand, sale_schedules, havenly_audience)
    result = evaluate_series(
        daily_counts, sale_fn,
        recent_window_days=defaults["recent_window_days"],
        baseline_weeks=defaults["baseline_weeks"],
        drop_threshold_pct=defaults["drop_threshold_pct"],
    )

    if result["status"] in ("zero", "drop"):
        if _already_alerted_today(state, key, today_str):
            logger.info(f"[{brand}] {name}: anomaly ({result['status']}) already alerted today — skipping")
        else:
            text = _format_alert(kind, name, brand, result, freshness)
            if dry_run:
                logger.info(f"[DRY RUN] Would post: {text}")
            elif post_message(text):
                logger.info(f"[{brand}] Posted anomaly alert for {name}")
                _mark_alerted(state, key, today_str)
    else:
        logger.info(
            f"[{brand}] {name}: {result['status']} "
            f"(recent_avg={result.get('recent_avg')}, baseline_avg={result.get('baseline_avg')})"
        )

    return result


def check_event(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run) -> dict:
    event_name = entry["event_name"]
    havenly_audience = entry.get("havenly_audience")
    is_purchase = entry.get("source") == "purchase"
    key = f"{brand}|event|{event_name}"

    view = PURCHASE_VIEW if is_purchase else EVENT_VIEW
    freshness = check_freshness(
        client, view, brand,
        skip_hours=defaults["freshness_skip_hours"],
        stale_hours=defaults["freshness_stale_hours"],
    )

    if is_purchase:
        # USERS_BEHAVIORS_PURCHASE_SHARED has no event-name column — it's a
        # single homogeneous purchase event type, not filterable by name.
        query_fn = lambda: get_daily_counts(
            client, view, brand,
            weeks=defaults["baseline_weeks"] + 1,
        )
    else:
        query_fn = lambda: get_daily_counts(
            client, view, brand,
            extra_filter_sql="AND NAME = %(event_name)s",
            extra_params={"event_name": event_name},
            weeks=defaults["baseline_weeks"] + 1,
        )

    return _handle_freshness_and_alert(
        brand, "event", event_name, key, freshness, defaults, sale_schedules,
        havenly_audience, state, today_str, dry_run,
        query_fn=query_fn,
    )


def check_canvas(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run) -> dict:
    canvas_name = entry["canvas_name"]
    havenly_audience = entry.get("havenly_audience")
    key = f"{brand}|canvas_first_email|{canvas_name}"

    canvas_id = entry.get("canvas_id") or resolve_canvas_id(canvas_name, brand)
    if not canvas_id:
        logger.warning(f"[{brand}] Could not resolve canvas id for '{canvas_name}' — skipping")
        return {"status": "resolution_error", "reason": "canvas not found"}

    step_name = entry.get("first_email_step_override") or resolve_first_email_step(canvas_id, brand)
    if not step_name:
        logger.warning(f"[{brand}] Could not resolve first email step for '{canvas_name}' — skipping")
        return {"status": "resolution_error", "reason": "no email step found"}

    freshness = check_freshness(
        client, EMAIL_SEND_VIEW, brand,
        skip_hours=defaults["freshness_skip_hours"],
        stale_hours=defaults["freshness_stale_hours"],
    )
    return _handle_freshness_and_alert(
        brand, "canvas_first_email", canvas_name, key, freshness, defaults, sale_schedules,
        havenly_audience, state, today_str, dry_run,
        query_fn=lambda: get_daily_counts(
            client, EMAIL_SEND_VIEW, brand,
            extra_filter_sql="AND CANVAS_API_ID = %(canvas_id)s AND CANVAS_STEP_NAME = %(step_name)s",
            extra_params={"canvas_id": canvas_id, "step_name": step_name},
            weeks=defaults["baseline_weeks"] + 1,
        ),
    )


def run(dry_run: bool = False, brand_filter: Optional[str] = None) -> dict:
    config = load_config()
    defaults = {**DEFAULT_THRESHOLDS, **(config.get("defaults") or {})}
    state = load_state()
    sale_schedules = load_sale_schedules()
    today_str = datetime.now(timezone.utc).date().isoformat()

    client = get_snowflake_client(schema=SCHEMA_PRIMARY, database=DB_PRIMARY)

    summary = Counter()
    events_cfg = config.get("events") or {}
    canvases_cfg = config.get("canvases") or {}
    brands = [brand_filter] if brand_filter else sorted(set(events_cfg) | set(canvases_cfg))

    for brand in brands:
        for entry in (events_cfg.get(brand) or []):
            summary["checked"] += 1
            try:
                result = check_event(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run)
                summary[result["status"]] += 1
            except Exception:
                logger.exception(f"[{brand}] Error checking event {entry.get('event_name')}")
                summary["errors"] += 1

        for entry in (canvases_cfg.get(brand) or []):
            summary["checked"] += 1
            try:
                result = check_canvas(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run)
                summary[result["status"]] += 1
            except Exception:
                logger.exception(f"[{brand}] Error checking canvas {entry.get('canvas_name')}")
                summary["errors"] += 1

    if dry_run:
        logger.info("[DRY RUN] Not saving state file")
    else:
        save_state(state)

    return dict(summary)


def _main():
    parser = argparse.ArgumentParser(
        description="Alert #team-lifecycle when a watched Braze event/canvas volume anomaly is detected"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print instead of posting to Slack; don't persist state")
    parser.add_argument("--brand", type=str, default=None, help="Limit to one brand (e.g. ID)")
    args = parser.parse_args()
    summary = run(dry_run=args.dry_run, brand_filter=args.brand.upper() if args.brand else None)
    print(f"monitor_braze_anomalies complete: {summary}")


if __name__ == "__main__":
    _main()

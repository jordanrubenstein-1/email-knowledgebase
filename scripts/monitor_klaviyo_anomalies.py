#!/usr/bin/env python3
"""
monitor_klaviyo_anomalies.py — Slack alert when a configured Klaviyo metric's
volume (TI or TE) drops well below its 4-week trailing baseline (excluding
sale days), or stops firing entirely.

Klaviyo counterpart to scripts/braze_automation/monitor_braze_anomalies.py —
same evaluate_series() detection logic (scripts/utils/anomaly_detector.py),
same Slack webhook and dedup-state pattern, but pulls volume from Klaviyo's
Query Metric Aggregates API instead of the Snowflake datashare. No freshness
gate here — Klaviyo's API is real-time, not a once-daily batch feed.

Runs once daily via GitLab CI (see .gitlab-ci.yml, monitor-klaviyo-anomalies
job). Idempotent — dedups on "{brand}|metric|{name}" per calendar day
(data/klaviyo_anomaly_state.yaml).

Watch-lists live in data/klaviyo_anomaly_config.yaml.

Usage:
    uv run python scripts/monitor_klaviyo_anomalies.py [--dry-run] [--brand TI]
"""
import argparse
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from utils.klaviyo_client import KlaviyoClient
from utils.sale_matcher import load_sale_schedules, is_during_sale
from utils.slack_client import post_message
from utils.anomaly_detector import evaluate_series

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = PROJECT_ROOT / "data" / "klaviyo_anomaly_config.yaml"
STATE_FILE = PROJECT_ROOT / "data" / "klaviyo_anomaly_state.yaml"

DEFAULT_THRESHOLDS = {
    "drop_threshold_pct": 50,
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


def _sale_check_fn(brand: str, sale_schedules: list):
    def fn(day) -> bool:
        return is_during_sale(day.isoformat(), brand, sale_schedules)
    return fn


def _format_alert(metric_name: str, brand: str, result: dict) -> str:
    sale_note = "Currently in an active sale." if result.get("recent_in_sale") else "Not sale-related."

    if result["status"] == "zero":
        baseline = result.get("baseline_avg")
        baseline_note = f" (baseline ~{baseline:.0f}/day)" if baseline else ""
        return (
            f":rotating_light: Klaviyo anomaly — *{metric_name}* ({brand})\n"
            f"No events in the last 2 days{baseline_note}. {sale_note}"
        )

    pct = result.get("pct_of_baseline")
    baseline = result.get("baseline_avg")
    recent = result.get("recent_avg")
    return (
        f":rotating_light: Klaviyo anomaly — *{metric_name}* ({brand})\n"
        f"Last 2 days avg: {recent:.0f}/day — {pct:.0f}% of the 4-week trailing baseline ({baseline:.0f}/day)\n"
        f"{sale_note}"
    )


def check_metric(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run) -> dict:
    metric_name = entry["metric_name"]
    key = f"{brand}|metric|{metric_name}"

    daily_counts = client.get_daily_counts(metric_name, weeks=defaults["baseline_weeks"] + 1)
    if not daily_counts:
        logger.warning(f"[{brand}] {metric_name}: no data (metric not found or truly zero volume) — skipping")
        return {"status": "no_data"}

    sale_fn = _sale_check_fn(brand, sale_schedules)
    result = evaluate_series(
        daily_counts, sale_fn,
        recent_window_days=defaults["recent_window_days"],
        baseline_weeks=defaults["baseline_weeks"],
        drop_threshold_pct=defaults["drop_threshold_pct"],
    )

    if result["status"] in ("zero", "drop"):
        if _already_alerted_today(state, key, today_str):
            logger.info(f"[{brand}] {metric_name}: anomaly ({result['status']}) already alerted today — skipping")
        else:
            text = _format_alert(metric_name, brand, result)
            if dry_run:
                logger.info(f"[DRY RUN] Would post: {text}")
            elif post_message(text):
                logger.info(f"[{brand}] Posted anomaly alert for {metric_name}")
                _mark_alerted(state, key, today_str)
    else:
        logger.info(
            f"[{brand}] {metric_name}: {result['status']} "
            f"(recent_avg={result.get('recent_avg')}, baseline_avg={result.get('baseline_avg')})"
        )

    return result


def run(dry_run: bool = False, brand_filter: Optional[str] = None) -> dict:
    config = load_config()
    defaults = {**DEFAULT_THRESHOLDS, **(config.get("defaults") or {})}
    state = load_state()
    sale_schedules = load_sale_schedules()
    today_str = datetime.now(timezone.utc).date().isoformat()

    summary = Counter()
    metrics_cfg = config.get("metrics") or {}
    brands = [brand_filter] if brand_filter else sorted(metrics_cfg)

    for brand in brands:
        api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
        if not api_key:
            logger.error(f"[{brand}] KLAVIYO_API_KEY_{brand} not set in .env — skipping brand")
            continue
        client = KlaviyoClient(api_key=api_key, brand=brand)

        for entry in (metrics_cfg.get(brand) or []):
            summary["checked"] += 1
            try:
                result = check_metric(client, brand, entry, defaults, sale_schedules, state, today_str, dry_run)
                summary[result["status"]] += 1
            except Exception:
                logger.exception(f"[{brand}] Error checking metric {entry.get('metric_name')}")
                summary["errors"] += 1

    if dry_run:
        logger.info("[DRY RUN] Not saving state file")
    else:
        save_state(state)

    return dict(summary)


def _main():
    parser = argparse.ArgumentParser(
        description="Alert #team-lifecycle when a watched Klaviyo metric volume anomaly is detected"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print instead of posting to Slack; don't persist state")
    parser.add_argument("--brand", type=str, default=None, help="Limit to one brand (TI or TE)")
    args = parser.parse_args()
    summary = run(dry_run=args.dry_run, brand_filter=args.brand.upper() if args.brand else None)
    print(f"monitor_klaviyo_anomalies complete: {summary}")


if __name__ == "__main__":
    _main()

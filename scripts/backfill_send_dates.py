#!/usr/bin/env python3
"""
Backfill send_date and inferred_send_type on all campaign YAMLs.

send_date: canonical analysis date parsed from campaign name (e.g. P_EM_2026_05_16_... → 2026-05-16).
More reliable than first_sent/last_sent for "when was this campaign sent?" analysis because
local-time and STO sends spread those values over 20–48h.

inferred_send_type: best-guess delivery mode based on first_sent/last_sent spread:
  scheduled   — spread < 15h  (fixed UTC time; covers queue delays for large lists)
  local_time  — spread 15–30h (rolling 24h window across time zones)
  sto         — spread > 30h  (exceeds 24h window, consistent with Intelligent Timing)
  None        — one or both timestamps missing, or campaign is a canvas step / triggered journey

Usage:
    uv run python scripts/backfill_send_dates.py
    uv run python scripts/backfill_send_dates.py --dry-run
    uv run python scripts/backfill_send_dates.py --brand ID
    uv run python scripts/backfill_send_dates.py --overwrite  # re-set even if already present
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml


CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

# Thresholds for inferred_send_type (hours between first_sent and last_sent)
LOCAL_TIME_MIN_H = 15   # below this = scheduled (fixed UTC + queue delay)
STO_MIN_H = 30          # above this = STO (Intelligent Timing)


def extract_date_from_name(name: str) -> str | None:
    """Extract YYYY-MM-DD from campaign name (e.g. P_EM_2026_05_16_ID_... → 2026-05-16)."""
    if not name:
        return None
    m = re.search(r"(\d{4})[-_](\d{1,2})[-_](\d{1,2})", name)
    if m:
        year, month, day = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def parse_dt(val) -> datetime | None:
    """Parse a datetime value from a YAML field (may be str or datetime object)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    try:
        s = str(val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def infer_send_type(dates: dict) -> str | None:
    """
    Infer delivery mode from first_sent/last_sent spread.
    Returns 'scheduled', 'local_time', 'sto', or None.
    """
    fs = parse_dt(dates.get("first_sent"))
    ls = parse_dt(dates.get("last_sent"))
    if fs is None or ls is None:
        return None
    spread_h = (ls - fs).total_seconds() / 3600
    if spread_h < 0:
        return None
    if spread_h < LOCAL_TIME_MIN_H:
        return "scheduled"
    if spread_h < STO_MIN_H:
        return "local_time"
    return "sto"


def build_ordered_dates(dates: dict, send_date: str | None, send_type: str | None) -> dict:
    """Return dates dict with canonical key order."""
    ordered = {}
    if "created" in dates:
        ordered["created"] = dates["created"]
    if send_date is not None:
        ordered["send_date"] = send_date
    elif "send_date" in dates:
        ordered["send_date"] = dates["send_date"]
    if send_type is not None:
        ordered["inferred_send_type"] = send_type
    elif "inferred_send_type" in dates:
        ordered["inferred_send_type"] = dates["inferred_send_type"]
    for key in ("first_sent", "last_sent"):
        if key in dates:
            ordered[key] = dates[key]
    # carry over any other keys
    for key, val in dates.items():
        if key not in ordered:
            ordered[key] = val
    return ordered


def load_yaml(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"  ERROR reading {path.name}: {e}", file=sys.stderr)
        return None


def save_yaml(path: Path, data: dict) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return True
    except Exception as e:
        print(f"  ERROR writing {path.name}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Backfill send_date and inferred_send_type on campaign YAMLs")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--brand", help="Only process campaigns for this brand (e.g. ID, HAV)")
    parser.add_argument("--overwrite", action="store_true", help="Re-set fields even if already present")
    args = parser.parse_args()

    yaml_files = sorted(CAMPAIGNS_DIR.glob("*.yaml"))
    print(f"Found {len(yaml_files)} YAML files in campaigns/\n")

    total = 0
    updated = 0
    skipped_already_set = 0
    skipped_no_change = 0
    errors = 0

    send_type_counts: dict[str, int] = {}

    for path in yaml_files:
        total += 1
        data = load_yaml(path)
        if data is None:
            errors += 1
            continue

        name = data.get("name", "")
        brand = data.get("brand", "")

        if args.brand and brand != args.brand.upper():
            continue

        dates = data.get("dates") or {}
        has_send_date = "send_date" in dates
        has_send_type = "inferred_send_type" in dates

        if has_send_date and has_send_type and not args.overwrite:
            skipped_already_set += 1
            continue

        # Compute new values
        send_date = extract_date_from_name(name) if (not has_send_date or args.overwrite) else None
        send_type = infer_send_type(dates) if (not has_send_type or args.overwrite) else None

        # Skip if nothing new to add
        if send_date is None and send_type is None:
            skipped_no_change += 1
            continue

        # Check if values actually changed
        if send_date == dates.get("send_date"):
            send_date = None
        if send_type == dates.get("inferred_send_type"):
            send_type = None
        if send_date is None and send_type is None:
            skipped_no_change += 1
            continue

        new_dates = build_ordered_dates(dates, send_date, send_type)

        send_type_counts[new_dates.get("inferred_send_type", "none")] = \
            send_type_counts.get(new_dates.get("inferred_send_type", "none"), 0) + 1

        if args.dry_run:
            parts = []
            if send_date:
                parts.append(f"send_date={send_date}")
            if send_type:
                parts.append(f"inferred_send_type={send_type}")
            print(f"  {name[:65]}  →  {', '.join(parts)}")
        else:
            data["dates"] = new_dates
            if save_yaml(path, data):
                updated += 1
            else:
                errors += 1
            continue

        updated += 1

    print(f"\nResults:")
    print(f"  Total YAMLs scanned    : {total}")
    print(f"  Updated                : {updated}")
    print(f"  Already complete       : {skipped_already_set}")
    print(f"  No change (no date)    : {skipped_no_change}")
    print(f"  Errors                 : {errors}")
    if send_type_counts:
        print(f"\n  inferred_send_type breakdown:")
        for k, v in sorted(send_type_counts.items()):
            print(f"    {k:15s}: {v}")
    if args.dry_run:
        print("\n(dry-run — no files written)")


if __name__ == "__main__":
    main()

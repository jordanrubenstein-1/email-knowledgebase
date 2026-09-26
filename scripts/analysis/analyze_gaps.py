#!/usr/bin/env python3
"""
Send Calendar Gap Analysis

Compares scheduled Asana tasks for the next N weeks against lifecycle guideline
targets and reports gaps with content-type suggestions.

Usage:
    uv run python scripts/analysis/analyze_gaps.py
    uv run python scripts/analysis/analyze_gaps.py --brand STF --weeks-ahead 2
    uv run python scripts/analysis/analyze_gaps.py --report
"""

import os
import sys
import argparse
import glob as glob_mod
import time
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
import requests
import yaml

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Import sale matcher utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.utils.sale_matcher import (
    load_sale_schedules,
    parse_campaign_date,
    parse_sale_date,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"

FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_CATEGORY = "1207522425689885"

BRAND_OPTIONS = {
    "HAV": "1207522425689881",
    "CZ": "1207553690167887",
    "ID": "1207522425689882",
    "BUR": "1208572919795447",
    "TI": "1207522425689883",
    "STF": "1207881071843537",
    "TRADE": "1208130746998739",
}
BRAND_GID_TO_CODE = {v: k for k, v in BRAND_OPTIONS.items()}

CHANNEL_EMAIL = "1207562370794989"

CATEGORY_OPTIONS = {
    "sale_merch": "1207522425689886",
    "editorial": "1207522425689887",
    "product_launch": "1207522425689888",
    "product_category": "1207522425689889",
    "dps": "1207522425689891",
    "trade": "1209467829907871",
}
CATEGORY_GID_TO_KEY = {v: k for k, v in CATEGORY_OPTIONS.items()}

# Lifecycle guideline brand name → brand code
# HAV is split: DPS = Pre-Converted, MP = Converted (Marketplace)
GUIDELINE_BRAND_MAP = {
    "Havenly Pre-Converted": "HAV-DPS",
    "Havenly Converted": "HAV-MP",
    "Interior Define": "ID",
    "Burrow": "BUR",
    "The Citizenry": "CZ",
    "The Inside": "TI",
    "St. Frank": "STF",
    "Trade Program": "TRADE",
}

# Sale schedule brand → brand code(s) for matching
# Values can be a string or list of strings for multi-match
SALE_BRAND_MAP = {
    "HAV": ["HAV-DPS", "HAV-MP"],  # Generic HAV matches both
    "HAVENLY DPS": "HAV-DPS",
    "HAVENLY MARKETPLACE": "HAV-MP",
    "ID": "ID",
    "BUR": "BUR",
    "CZ": "CZ",
    "TI": "TI",
    "STF": "STF",
    "TRADE": "TRADE",
}

# Content type labels for suggestions
CONTENT_TYPES = {
    "sale_merch": "Sale/Promo (featured sale items, discount highlight)",
    "editorial": "Editorial/Content (trend report, style guide, room inspiration)",
    "product_launch": "New Product/Launch (new arrival, collection debut)",
    "product_category": "Product/Category feature (category spotlight, curated edit)",
    "reminder": "Reminder/Last Chance (sale ends, limited stock)",
    "dps": "DPS send (design package service promotion)",
}


# ---------------------------------------------------------------------------
# Asana API helpers
# ---------------------------------------------------------------------------

def get_asana_token() -> str:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return token


def asana_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_asana_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def asana_request(method: str, endpoint: str, json_data: Optional[dict] = None,
                  params: Optional[dict] = None) -> Optional[Any]:
    """Make an Asana API request with rate-limit handling."""
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=asana_headers(),
                            json=json_data, params=params)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {retry_after}s...")
        time.sleep(retry_after)
        resp = requests.request(method, url, headers=asana_headers(),
                                json=json_data, params=params)

    if resp.status_code not in (200, 201):
        print(f"  Asana error {resp.status_code}: {resp.text[:300]}")
        return None

    return resp.json().get("data")


# ---------------------------------------------------------------------------
# Channel discovery
# ---------------------------------------------------------------------------

def discover_channel_options() -> Dict[str, str]:
    """Fetch Channel custom field definition to get all enum option GIDs.

    Returns dict like {"email": "123", "sms": "456", "push": "789"}.
    """
    data = asana_request("GET", f"custom_fields/{FIELD_CHANNEL}")
    if not data:
        print("  Warning: Could not fetch Channel field — using Email only")
        return {"email": CHANNEL_EMAIL}

    options = {}
    for opt in data.get("enum_options", []):
        name = opt.get("name", "").strip().lower()
        gid = opt.get("gid")
        if name and gid:
            options[name] = gid
    return options


# ---------------------------------------------------------------------------
# Fetch & parse Asana tasks
# ---------------------------------------------------------------------------

def fetch_asana_tasks(
    weeks: List[Tuple[date, date, str]],
) -> List[Dict]:
    """Fetch tasks from Asana for each week separately to avoid the 100-result limit."""
    all_tasks = []
    seen_gids = set()

    for week_start, week_end, label in weeks:
        params = {
            "projects.any": ASANA_PROJECT_GID,
            "due_on.after": week_start.isoformat(),
            "due_on.before": week_end.isoformat(),
            "opt_fields": (
                "name,due_on,completed,"
                "custom_fields,custom_fields.name,"
                "custom_fields.display_value,"
                "custom_fields.enum_value,"
                "custom_fields.enum_value.gid,"
                "custom_fields.enum_value.name"
            ),
            "limit": "100",
            "sort_by": "due_date",
            "sort_ascending": "true",
        }

        data = asana_request(
            "GET",
            f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search",
            params=params,
        )
        if data is None:
            continue
        for task in data:
            gid = task.get("gid")
            if gid not in seen_gids:
                seen_gids.add(gid)
                all_tasks.append(task)

    return all_tasks


def extract_custom_field_gid(task: Dict, field_gid: str) -> Optional[str]:
    """Extract the selected enum GID for a custom field from a task."""
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            ev = cf.get("enum_value")
            if ev:
                return ev.get("gid")
    return None


def parse_tasks(tasks: List[Dict], channel_options: Dict[str, str]) -> List[Dict]:
    """Parse raw Asana tasks into normalized dicts."""
    # Reverse channel map: GID → normalized name
    channel_gid_to_name = {gid: name for name, gid in channel_options.items()}

    parsed = []
    for task in tasks:
        due_on = task.get("due_on")
        if not due_on:
            continue

        brand_gid = extract_custom_field_gid(task, FIELD_BRAND)
        brand_code = BRAND_GID_TO_CODE.get(brand_gid, "UNKNOWN")

        # Split HAV into DPS (Pre-Converted) and MP (Marketplace/Converted)
        task_name = task.get("name", "")
        if brand_code == "HAV":
            name_upper = task_name.upper()
            if name_upper.startswith("DPS") or "DPS " in name_upper:
                brand_code = "HAV-DPS"
            elif name_upper.startswith("MP") or "MP " in name_upper:
                brand_code = "HAV-MP"
            else:
                # Default: MP (marketplace/converted) for non-prefixed HAV tasks
                brand_code = "HAV-MP"

        channel_gid = extract_custom_field_gid(task, FIELD_CHANNEL)
        channel = channel_gid_to_name.get(channel_gid, "unknown")

        category_gid = extract_custom_field_gid(task, FIELD_CATEGORY)
        category = CATEGORY_GID_TO_KEY.get(category_gid, "unknown")

        parsed.append({
            "name": task_name,
            "due_on": due_on,
            "brand": brand_code,
            "channel": channel,
            "category": category,
        })

    return parsed


# ---------------------------------------------------------------------------
# Lifecycle guidelines
# ---------------------------------------------------------------------------

def parse_range(value: str) -> Optional[Tuple[int, int]]:
    """Parse a range string like '5-9' or '3' into (min, max) tuple."""
    if not value:
        return None
    value = str(value).strip()
    if "-" in value:
        parts = value.split("-")
        try:
            return (int(parts[0].strip()), int(parts[1].strip()))
        except (ValueError, IndexError):
            return None
    try:
        n = int(value)
        return (n, n)
    except ValueError:
        return None


def load_guidelines() -> Dict[str, Dict[str, Any]]:
    """Load lifecycle guidelines into per-brand-code targets.

    Returns dict like:
        {"HAV": {"email": (5, 9), "sms": None, "push": (1, 2)}, ...}
    """
    guidelines_path = Path(__file__).parent.parent.parent / "data" / "lifecycle_guidelines.yaml"
    with open(guidelines_path) as f:
        data = yaml.safe_load(f)

    targets: Dict[str, Dict[str, Any]] = {}

    for brand_entry in data.get("brands", []):
        name = brand_entry.get("name", "")
        code = GUIDELINE_BRAND_MAP.get(name)
        if not code:
            continue

        cadence = brand_entry.get("send_cadence", {})
        email_range = parse_range(cadence.get("emails_per_week", ""))

        segments = brand_entry.get("segments", {})
        sms_range = parse_range(segments.get("sms", {}).get("sends_per_week", "")) if "sms" in segments else None
        push_range = parse_range(segments.get("push", {}).get("sends_per_week", "")) if "push" in segments else None

        if code in targets:
            # HAV: merge Pre-Conv + Converted — take wider range
            existing = targets[code]
            if email_range and existing.get("email"):
                existing["email"] = (
                    min(existing["email"][0], email_range[0]),
                    max(existing["email"][1], email_range[1]),
                )
            elif email_range:
                existing["email"] = email_range
            if push_range and not existing.get("push"):
                existing["push"] = push_range
            if sms_range and not existing.get("sms"):
                existing["sms"] = sms_range
        else:
            targets[code] = {
                "email": email_range,
                "sms": sms_range,
                "push": push_range,
            }

    return targets


# ---------------------------------------------------------------------------
# Week boundaries & grouping
# ---------------------------------------------------------------------------

def get_week_boundaries(start_date: date, weeks_ahead: int) -> List[Tuple[date, date, str]]:
    """Return (monday, sunday, label) for the next N weeks."""
    monday = start_date - timedelta(days=start_date.weekday())
    weeks = []
    for i in range(weeks_ahead):
        week_start = monday + timedelta(weeks=i)
        week_end = week_start + timedelta(days=6)
        label = f"Week of {week_start.strftime('%b %d')}"
        weeks.append((week_start, week_end, label))
    return weeks


def group_tasks(
    tasks: List[Dict],
    weeks: List[Tuple[date, date, str]],
) -> Dict[str, Dict[str, Dict[str, List[Dict]]]]:
    """Group tasks into brand → week_label → channel → [tasks]."""
    grouped: Dict[str, Dict[str, Dict[str, List[Dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for task in tasks:
        due = date.fromisoformat(task["due_on"])
        for week_start, week_end, label in weeks:
            if week_start <= due <= week_end:
                grouped[task["brand"]][label][task["channel"]].append(task)
                break

    return grouped


# ---------------------------------------------------------------------------
# Sale context
# ---------------------------------------------------------------------------

def sale_matches_brand(sale_brand: str, brand_code: str) -> bool:
    """Check if a sale schedule entry matches a brand code.

    Handles inconsistent naming: 'HAVENLY DPS' → HAV-DPS, 'BFCM' → all brands, etc.
    """
    mapped = SALE_BRAND_MAP.get(sale_brand)
    if mapped:
        if isinstance(mapped, list):
            return brand_code in mapped
        return mapped == brand_code
    # Cross-brand sales (event names like BFCM, BRAND, etc.) match all brands
    if sale_brand in ("BRAND",):
        return True
    # Event-style names (no direct brand match) — treat as cross-brand
    if sale_brand not in SALE_BRAND_MAP:
        return True
    return False


def get_sale_context_for_week(
    week_start: date, week_end: date, brand_code: str,
    sale_schedules: List[Dict],
) -> Tuple[bool, List[str]]:
    """Check if any day in the week falls during a sale for this brand.

    Returns (during_sale, [sale_names]).
    """
    sale_names = []
    for sale in sale_schedules:
        if not sale_matches_brand(sale.get("brand", ""), brand_code):
            continue

        s_start = parse_sale_date(sale.get("start_date"))
        s_end = parse_sale_date(sale.get("end_date")) or s_start
        if not s_start:
            continue

        # Check overlap: sale and week ranges
        if s_start.date() <= week_end and s_end.date() >= week_start:
            sale_names.append(sale.get("name", sale.get("brand", "Sale")))

    return bool(sale_names), sale_names


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------

def compute_gaps(
    grouped: Dict[str, Dict[str, Dict[str, List[Dict]]]],
    targets: Dict[str, Dict[str, Any]],
    weeks: List[Tuple[date, date, str]],
    sale_schedules: List[Dict],
) -> List[Dict[str, Any]]:
    """Compute gaps for each brand × week × channel."""
    gaps = []

    for brand_code, brand_targets in targets.items():
        # Build list of (channel_name, (min, max)) targets for this brand
        channel_targets = []
        for ch in ("email", "sms", "push"):
            t = brand_targets.get(ch)
            if t:
                channel_targets.append((ch, t))

        for week_start, week_end, week_label in weeks:
            during_sale, sale_names = get_sale_context_for_week(
                week_start, week_end, brand_code, sale_schedules
            )

            for channel, (target_min, target_max) in channel_targets:
                tasks_in_slot = grouped.get(brand_code, {}).get(week_label, {}).get(channel, [])
                scheduled = len(tasks_in_slot)

                cat_counts: Dict[str, int] = defaultdict(int)
                for t in tasks_in_slot:
                    cat_counts[t["category"]] += 1

                gap = max(0, target_min - scheduled)
                if scheduled < target_min:
                    status = "under"
                elif scheduled > target_max:
                    status = "over"
                else:
                    status = "on_target"

                gaps.append({
                    "brand": brand_code,
                    "week_label": week_label,
                    "week_start": week_start,
                    "week_end": week_end,
                    "channel": channel,
                    "scheduled": scheduled,
                    "target_min": target_min,
                    "target_max": target_max,
                    "gap": gap,
                    "status": status,
                    "during_sale": during_sale,
                    "sale_names": sale_names,
                    "scheduled_categories": dict(cat_counts),
                    "tasks": tasks_in_slot,
                })

    return gaps


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def load_historical_category_mix(brand: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load historical category distribution from campaign YAMLs."""
    campaigns_dir = Path(__file__).parent.parent.parent / "campaigns"
    brand_cat_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for yaml_file in glob_mod.glob(str(campaigns_dir / "*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not data or data.get("channel") != "email":
            continue
        if data.get("braze_type") == "canvas_step":
            continue

        b = data.get("brand", "")
        cat = data.get("category", "other")
        if brand and b != brand:
            continue
        brand_cat_counts[b][cat] += 1

    result = {}
    for b, cats in brand_cat_counts.items():
        total = sum(cats.values())
        if total > 0:
            result[b] = {cat: count / total for cat, count in cats.items()}

    # HAV-DPS and HAV-MP share the same historical mix as HAV
    if "HAV" in result:
        result["HAV-DPS"] = result["HAV"]
        result["HAV-MP"] = result["HAV"]

    return result


def suggest_content_fills(gap: Dict, historical_mix: Dict[str, Dict[str, float]],
                          inventory_summary: Optional[Dict[str, Dict]] = None) -> List[str]:
    """Generate content suggestions for under-target gaps.

    Args:
        gap: Gap dict with brand, scheduled_categories, during_sale, etc.
        historical_mix: Historical category distribution by brand.
        inventory_summary: Optional dict of brand → {top_categories, top_products}.
    """
    brand = gap["brand"]
    scheduled_cats = gap["scheduled_categories"]
    during_sale = gap["during_sale"]
    remaining = gap["gap"]

    if remaining == 0:
        return []

    suggestions = []
    brand_mix = historical_mix.get(brand, {})

    # During sales: prioritize sale/reminder content
    if during_sale:
        sale_scheduled = scheduled_cats.get("sale_merch", 0) + scheduled_cats.get("reminder", 0)
        sale_fills = min(remaining, max(1, remaining // 2))
        if sale_scheduled < 2:
            sale_label = ", ".join(gap["sale_names"][:2])
            suggestions.append(f"  + {sale_fills}x Sale/Promo or Reminder (sale: {sale_label})")
            remaining -= sale_fills

    # Fill remaining based on under-represented categories
    if remaining > 0:
        total_scheduled = sum(scheduled_cats.values())
        # Rank categories by how under-represented they are
        category_deficit = []
        for cat in ("editorial", "product_category", "product_launch", "sale_merch", "dps"):
            hist_pct = brand_mix.get(cat, 0)
            scheduled_count = scheduled_cats.get(cat, 0)
            expected = hist_pct * (total_scheduled + gap["gap"])
            deficit = expected - scheduled_count
            if deficit > 0 and cat in CONTENT_TYPES:
                category_deficit.append((deficit, cat))

        category_deficit.sort(reverse=True)

        for _, cat in category_deficit:
            if remaining <= 0:
                break
            # Append top stocked categories for product-related suggestions
            inv_hint = ""
            if cat in ("product_category", "product_launch") and inventory_summary:
                # Map HAV-DPS / HAV-MP to HAV for inventory lookup
                inv_brand = brand.split("-")[0] if "-" in brand else brand
                brand_inv = inventory_summary.get(inv_brand)
                if brand_inv and brand_inv.get("top_categories"):
                    top_cats = ", ".join(brand_inv["top_categories"][:3])
                    inv_hint = f" — top stocked: {top_cats}"
            suggestions.append(f"  + 1x {CONTENT_TYPES[cat]}{inv_hint}")
            remaining -= 1

    # Generic fills if still gaps
    generic_order = ["editorial", "product_category", "product_launch"]
    for cat in generic_order:
        if remaining <= 0:
            break
        if cat not in [s.split("x ")[1].split(" (")[0] if "x " in s else "" for s in suggestions]:
            inv_hint = ""
            if cat in ("product_category", "product_launch") and inventory_summary:
                inv_brand = brand.split("-")[0] if "-" in brand else brand
                brand_inv = inventory_summary.get(inv_brand)
                if brand_inv and brand_inv.get("top_categories"):
                    top_cats = ", ".join(brand_inv["top_categories"][:3])
                    inv_hint = f" — top stocked: {top_cats}"
            suggestions.append(f"  + 1x {CONTENT_TYPES[cat]}{inv_hint}")
            remaining -= 1

    return suggestions


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_terminal_report(gaps: List[Dict], historical_mix: Dict,
                          inventory_summary: Optional[Dict[str, Dict]] = None) -> None:
    """Print terminal summary."""
    brands = sorted(set(g["brand"] for g in gaps))

    print("\n" + "=" * 70)
    print("  SEND CALENDAR GAP ANALYSIS")
    print("=" * 70)

    for brand in brands:
        brand_gaps = [g for g in gaps if g["brand"] == brand]
        has_issues = any(g["status"] == "under" for g in brand_gaps)

        header = f"  {brand}"
        if has_issues:
            under_count = sum(g["gap"] for g in brand_gaps if g["status"] == "under")
            header += f" — {under_count} missing sends"
        else:
            header += " — OK"
        print(f"\n{'—' * 70}")
        print(header)
        print(f"{'—' * 70}")

        for gap in brand_gaps:
            ch = gap["channel"].upper()
            sale_marker = " [SALE]" if gap["during_sale"] else ""

            if gap["status"] == "under":
                icon = "!!"
                detail = f"UNDER by {gap['gap']} ({gap['scheduled']}/{gap['target_min']}-{gap['target_max']})"
            elif gap["status"] == "over":
                icon = ">>"
                detail = f"OVER ({gap['scheduled']}/{gap['target_min']}-{gap['target_max']})"
            else:
                icon = "OK"
                detail = f"on target ({gap['scheduled']}/{gap['target_min']}-{gap['target_max']})"

            print(f"  {icon} {gap['week_label']}{sale_marker} | {ch}: {detail}")

            # Show scheduled tasks for under-target weeks
            if gap["status"] == "under" and gap["tasks"]:
                for t in gap["tasks"]:
                    print(f"       - {t['name']} ({t['category']})")

            # Show suggestions
            if gap["status"] == "under":
                for s in suggest_content_fills(gap, historical_mix, inventory_summary):
                    print(f"     {s}")

    # Summary
    total_gaps = sum(g["gap"] for g in gaps if g["status"] == "under")
    sale_gaps = sum(g["gap"] for g in gaps if g["status"] == "under" and g["during_sale"])

    print(f"\n{'=' * 70}")
    print(f"  TOTAL: {total_gaps} missing sends across all brands")
    if sale_gaps:
        print(f"  CRITICAL: {sale_gaps} of those are during active sale periods")
    print(f"{'=' * 70}\n")


def generate_markdown_report(gaps: List[Dict], historical_mix: Dict,
                             inventory_summary: Optional[Dict[str, Dict]] = None) -> str:
    """Generate markdown report."""
    lines = []
    today = date.today()

    lines.append("# Send Calendar Gap Analysis")
    lines.append(f"> Generated {today.strftime('%B %d, %Y')}")
    lines.append("")

    # Summary
    total_gaps = sum(g["gap"] for g in gaps if g["status"] == "under")
    sale_gaps = sum(g["gap"] for g in gaps if g["status"] == "under" and g["during_sale"])
    brands_with_gaps = sorted(set(g["brand"] for g in gaps if g["status"] == "under"))

    lines.append("## Summary")
    lines.append("")
    if total_gaps:
        lines.append(f"- **{total_gaps} missing sends** across {len(brands_with_gaps)} brand(s): {', '.join(brands_with_gaps)}")
        if sale_gaps:
            lines.append(f"- **{sale_gaps} gaps during sale periods** (high priority)")
    else:
        lines.append("All brands are on target for the analyzed period.")
    lines.append("")

    # Overview table
    lines.append("## Overview")
    lines.append("")
    lines.append("| Brand | Week | Channel | Scheduled | Target | Gap | Sale? |")
    lines.append("|-------|------|---------|-----------|--------|-----|-------|")

    for g in sorted(gaps, key=lambda x: (x["brand"], x["week_start"], x["channel"])):
        gap_text = f"**-{g['gap']}**" if g["status"] == "under" else ("+" + str(g["scheduled"] - g["target_max"]) if g["status"] == "over" else "—")
        sale = "Yes" if g["during_sale"] else ""
        lines.append(
            f"| {g['brand']} | {g['week_label']} | {g['channel']} | "
            f"{g['scheduled']} | {g['target_min']}-{g['target_max']} | "
            f"{gap_text} | {sale} |"
        )
    lines.append("")

    # Detailed gaps with suggestions
    under_gaps = [g for g in gaps if g["status"] == "under"]
    if under_gaps:
        lines.append("## Gaps & Suggestions")
        lines.append("")

        for brand in sorted(set(g["brand"] for g in under_gaps)):
            brand_gaps = [g for g in under_gaps if g["brand"] == brand]
            lines.append(f"### {brand}")
            lines.append("")

            for g in brand_gaps:
                sale_note = f" (Sale: {', '.join(g['sale_names'][:2])})" if g["during_sale"] else ""
                lines.append(
                    f"**{g['week_label']}** — {g['channel'].upper()}: "
                    f"{g['scheduled']}/{g['target_min']} scheduled{sale_note}"
                )
                lines.append("")

                if g["tasks"]:
                    lines.append("Currently scheduled:")
                    for t in g["tasks"]:
                        lines.append(f"- {t['name']} ({t['category']})")
                    lines.append("")

                suggestions = suggest_content_fills(g, historical_mix, inventory_summary)
                if suggestions:
                    lines.append("Suggested fills:")
                    for s in suggestions:
                        lines.append(f"- {s.strip()}")
                    lines.append("")

    # Inventory status section
    if inventory_summary:
        lines.append("## Inventory Status")
        lines.append("")
        for inv_brand in sorted(inventory_summary.keys()):
            inv = inventory_summary[inv_brand]
            if inv:
                cats = ", ".join(inv.get("top_categories", [])[:5])
                prods = ", ".join(inv.get("top_products", [])[:3])
                lines.append(f"**{inv_brand}**: Top categories: {cats}")
                if prods:
                    lines.append(f"  Top products: {prods}")
                lines.append("")

    lines.append("---")
    lines.append(f"*Based on lifecycle guidelines vs {len(gaps)} brand/week/channel slots.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze send calendar gaps against lifecycle targets"
    )
    parser.add_argument("--brand", type=str,
                        help="Filter to one brand (HAV, CZ, ID, BUR, TI, STF, TRADE)")
    parser.add_argument("--weeks-ahead", type=int, default=4,
                        help="Number of weeks to analyze (default: 4)")
    parser.add_argument("--report", action="store_true",
                        help="Save markdown report to reports/")
    parser.add_argument("--skip-inventory", action="store_true",
                        help="Skip inventory lookup (don't show stocked product categories)")

    args = parser.parse_args()

    # 1. Week boundaries
    today = date.today()
    weeks = get_week_boundaries(today, args.weeks_ahead)
    print(f"Analyzing {args.weeks_ahead} weeks: {weeks[0][0]} to {weeks[-1][1]}")

    # 2. Discover channel options
    print("Discovering channel options...")
    channel_options = discover_channel_options()
    print(f"  Channels: {', '.join(channel_options.keys())}")

    # 3. Fetch Asana tasks (per-week to avoid 100-result limit)
    print("Fetching Asana tasks...")
    raw_tasks = fetch_asana_tasks(weeks)
    print(f"  Found {len(raw_tasks)} tasks")

    # 4. Parse tasks
    tasks = parse_tasks(raw_tasks, channel_options)

    # Filter by brand if specified (--brand HAV matches both HAV-DPS and HAV-MP)
    if args.brand:
        brand_upper = args.brand.upper()
        if brand_upper == "HAV":
            tasks = [t for t in tasks if t["brand"].startswith("HAV")]
        else:
            tasks = [t for t in tasks if t["brand"] == brand_upper]
    print(f"  Parsed {len(tasks)} tasks with due dates")

    # 5. Load guidelines and sale schedules
    targets = load_guidelines()
    sale_schedules = load_sale_schedules()

    if args.brand:
        brand_upper = args.brand.upper()
        if brand_upper == "HAV":
            targets = {k: v for k, v in targets.items() if k.startswith("HAV")}
        else:
            targets = {k: v for k, v in targets.items() if k == brand_upper}

    # 6. Group and compute gaps
    grouped = group_tasks(tasks, weeks)
    gaps = compute_gaps(grouped, targets, weeks, sale_schedules)

    # 7. Historical mix for suggestions
    print("Loading historical category data...")
    historical_mix = load_historical_category_mix(args.brand.upper() if args.brand else None)

    # 8. Load inventory summaries (if enabled)
    inventory_summary: Optional[Dict[str, Dict]] = None
    if not args.skip_inventory:
        try:
            from scripts.utils.inventory_checker import (
                get_inventory_summary,
                close_all_clients as close_inventory_clients,
                SUPPORTED_BRANDS as INVENTORY_BRANDS,
            )
            inventory_summary = {}
            # Determine which brands we need inventory for
            inv_brands = set()
            for g in gaps:
                # Map HAV-DPS / HAV-MP to HAV
                base_brand = g["brand"].split("-")[0] if "-" in g["brand"] else g["brand"]
                if base_brand in INVENTORY_BRANDS:
                    inv_brands.add(base_brand)

            for inv_brand in sorted(inv_brands):
                try:
                    summary = get_inventory_summary(inv_brand)
                    if summary:
                        inventory_summary[inv_brand] = summary
                        print(f"  Loaded inventory for {inv_brand}: "
                              f"{len(summary.get('top_categories', []))} categories")
                except Exception as e:
                    print(f"  Warning: Could not load inventory for {inv_brand}: {e}")

            if not inventory_summary:
                inventory_summary = None
        except ImportError:
            print("  Note: inventory_checker not available — skipping inventory data.")
        except Exception as e:
            print(f"  Warning: Inventory loading failed: {e}")

    # 9. Output
    print_terminal_report(gaps, historical_mix, inventory_summary)

    if args.report:
        report = generate_markdown_report(gaps, historical_mix, inventory_summary)
        report_path = Path(__file__).parent.parent.parent / "reports" / "gap-analysis.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            f.write(report)
        print(f"Report saved to {report_path}")

    # Clean up inventory connections
    if inventory_summary:
        try:
            close_inventory_clients()
        except Exception:
            pass


if __name__ == "__main__":
    main()

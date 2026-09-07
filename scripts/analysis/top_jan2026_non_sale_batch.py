#!/usr/bin/env python3
"""
Top batch/blast email campaigns by brand, January 2026, non-sale periods only.

Excludes:
- EOY Sale Extension (and Year-End Refresh for CZ)
- Winter Refresh / Winter Retreat sales

Ranks top 5 per brand by click-through rate, sessions, and revenue.
Outputs: reports/top-jan2026-non-sale-batch-email.md
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

# Add parent for utils
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"
REPORT_PATH = Path(__file__).parent.parent.parent / "reports" / "top-jan2026-non-sale-batch-email.md"

# January 2026 sale periods to EXCLUDE (from user-provided calendar).
# Each entry: (brand, start_date_str, end_date_str) — inclusive.
# EOY Sale Extension and Year-End Refresh:
EOY_AND_YEAREND = [
    ("HAV", "2026-01-01", "2026-01-05"),
    ("ID", "2026-01-01", "2026-01-06"),
    ("BUR", "2026-01-01", "2026-01-05"),
    ("CZ", "2026-01-01", "2026-01-04"),   # Year-End Refresh Sale
    ("TI", "2026-01-01", "2026-01-05"),
    ("STF", "2026-01-01", "2026-01-05"),
]

# Winter Refresh / Winter Retreat (by brand)
# ID: 1/14–1/28 (incl. Winter_Refresh_Sale_Launch, Winter_Retreat_Sale_Final_Hours)
# CZ: 1/15–1/29 (incl. 1/15 PT Winter Refresh Sale)
# BUR: Flash Sale 1/28–2/5 added separately
WINTER_REFRESH_RETREAT = [
    ("HAV", "2026-01-13", "2026-01-27"),  # MKPL 1/13, DPS 1/14 — use 1/13
    ("ID", "2026-01-14", "2026-01-28"),
    ("BUR", "2026-01-15", "2026-01-27"),
    ("CZ", "2026-01-15", "2026-01-29"),
    ("TI", "2026-01-15", "2026-01-27"),
    ("STF", "2026-01-15", "2026-01-27"),
]
BUR_FLASH_SALE = [
    ("BUR", "2026-01-28", "2026-02-05"),
]

BRAND_NAMES = {
    "HAV": "Havenly",
    "ID": "Interior Define",
    "BUR": "Burrow",
    "CZ": "The Citizenry",
    "TI": "The Inside",
    "STF": "St Frank",
}


def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, AttributeError):
        return None


def date_in_range(d: datetime, start_str: str, end_str: str) -> bool:
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    day = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start <= day <= end


def is_during_excluded_sale(campaign: Dict[str, Any]) -> bool:
    """True if campaign first_sent falls in EOY or Winter Refresh/Retreat for its brand."""
    brand = campaign.get("brand")
    if not brand:
        return False
    dates = campaign.get("dates", {})
    first_sent = dates.get("first_sent")
    if not first_sent:
        return False
    d = parse_date(first_sent)
    if not d:
        return False
    for b, start, end in EOY_AND_YEAREND + WINTER_REFRESH_RETREAT + BUR_FLASH_SALE:
        if b == brand and date_in_range(d, start, end):
            return True
    return False


def load_campaigns_jan2026_batch_email() -> List[Dict[str, Any]]:
    campaigns = []
    for f in CAMPAIGNS_DIR.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        try:
            with open(f) as fp:
                data = yaml.safe_load(fp)
        except Exception:
            continue
        if not data:
            continue
        if data.get("channel") != "email":
            continue
        if data.get("braze_type") == "canvas_step":
            continue
        dates = data.get("dates", {})
        first_sent = dates.get("first_sent")
        if not first_sent:
            continue
        d = parse_date(first_sent)
        if not d or d.year != 2026 or d.month != 1:
            continue
        perf = data.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 100:
            continue
        data["_filename"] = str(f.name)
        campaigns.append(data)
    return campaigns


def get_ctr(c: Dict[str, Any]) -> float:
    perf = c.get("performance_summary", {})
    return float(perf.get("click_rate") or 0)


def get_sessions(c: Dict[str, Any]) -> int:
    ga4 = (c.get("performance_summary") or {}).get("ga4") or {}
    return int(ga4.get("sessions") or 0)


def get_revenue(c: Dict[str, Any]) -> float:
    ga4 = (c.get("performance_summary") or {}).get("ga4") or {}
    return float(ga4.get("revenue") or 0)


def top_n_by(campaigns: List[Dict], key_fn, n: int = 5, reverse: bool = True) -> List[Dict]:
    key = key_fn
    sorted_list = sorted(campaigns, key=key, reverse=reverse)
    return sorted_list[:n]


def write_report(
    by_brand: Dict[str, Dict[str, List[Dict]]],
    excluded_count: int,
    included_count: int,
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Top 5 Batch/Blast Email Campaigns by Brand — January 2026 (Non-Sale Only)",
        "",
        "Excluded sale periods:",
        "- **EOY Sale Extension** (and Year-End Refresh for The Citizenry)",
        "- **Winter Refresh / Winter Retreat**",
        "",
        f"Campaigns in Jan 2026 batch email: **{included_count}** (after excluding **{excluded_count}** sent during sale periods).",
        "",
        "---",
        "",
    ]
    for brand_code in ["HAV", "ID", "BUR", "CZ", "TI", "STF"]:
        brand_label = BRAND_NAMES.get(brand_code, brand_code)
        data = by_brand.get(brand_code, {})
        top_ctr = data.get("by_ctr", [])
        top_sessions = data.get("by_sessions", [])
        top_revenue = data.get("by_revenue", [])
        if not top_ctr and not top_sessions and not top_revenue:
            lines.append(f"## {brand_label} ({brand_code})")
            lines.append("")
            lines.append("No batch email campaigns in January 2026 during non-sale periods.")
            lines.append("")
            continue
        lines.append(f"## {brand_label} ({brand_code})")
        lines.append("")
        if top_ctr:
            lines.append("### Top 5 by click-through rate")
            lines.append("")
            lines.append("| Campaign | First sent | CTR | Sends | Sessions | Revenue |")
            lines.append("|---------|------------|-----|-------|----------|---------|")
            for c in top_ctr:
                name = (c.get("name") or "")[:60]
                first = (c.get("dates") or {}).get("first_sent", "")[:10]
                ctr = get_ctr(c)
                sends = (c.get("performance_summary") or {}).get("total_sends", 0)
                sess = get_sessions(c)
                rev = get_revenue(c)
                lines.append(f"| {name} | {first} | {ctr:.2%} | {sends:,} | {sess:,} | ${rev:,.2f} |")
            lines.append("")
        if top_sessions:
            lines.append("### Top 5 by sessions (GA4)")
            lines.append("")
            lines.append("| Campaign | First sent | Sessions | Revenue | CTR | Sends |")
            lines.append("|---------|------------|----------|---------|-----|-------|")
            for c in top_sessions:
                name = (c.get("name") or "")[:60]
                first = (c.get("dates") or {}).get("first_sent", "")[:10]
                sess = get_sessions(c)
                rev = get_revenue(c)
                ctr = get_ctr(c)
                sends = (c.get("performance_summary") or {}).get("total_sends", 0)
                lines.append(f"| {name} | {first} | {sess:,} | ${rev:,.2f} | {ctr:.2%} | {sends:,} |")
            lines.append("")
        if top_revenue:
            lines.append("### Top 5 by revenue (GA4)")
            lines.append("")
            lines.append("| Campaign | First sent | Revenue | Sessions | CTR | Sends |")
            lines.append("|---------|------------|---------|----------|-----|-------|")
            for c in top_revenue:
                name = (c.get("name") or "")[:60]
                first = (c.get("dates") or {}).get("first_sent", "")[:10]
                rev = get_revenue(c)
                sess = get_sessions(c)
                ctr = get_ctr(c)
                sends = (c.get("performance_summary") or {}).get("total_sends", 0)
                lines.append(f"| {name} | {first} | ${rev:,.2f} | {sess:,} | {ctr:.2%} | {sends:,} |")
            lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


def main() -> None:
    campaigns = load_campaigns_jan2026_batch_email()
    non_sale = [c for c in campaigns if not is_during_excluded_sale(c)]
    excluded_count = len(campaigns) - len(non_sale)
    included_count = len(non_sale)

    by_brand: Dict[str, Dict[str, List[Dict]]] = {}
    for brand_code in ["HAV", "ID", "BUR", "CZ", "TI", "STF"]:
        subset = [c for c in non_sale if c.get("brand") == brand_code]
        by_brand[brand_code] = {
            "by_ctr": top_n_by(subset, get_ctr, 5),
            "by_sessions": top_n_by(subset, get_sessions, 5),
            "by_revenue": top_n_by(subset, get_revenue, 5),
        }

    write_report(by_brand, excluded_count, included_count)


if __name__ == "__main__":
    main()

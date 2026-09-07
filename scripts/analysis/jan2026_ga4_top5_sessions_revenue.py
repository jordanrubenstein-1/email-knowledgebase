#!/usr/bin/env python3
"""
January 2026: Top 5 by sessions and top 5 by revenue, per brand (GA4 brands only).
Split by ON-SALE vs OFF-SALE period. Output: campaign name, sessions, revenue $.

GA4 brands: ID (Interior Define), BUR (Burrow), CZ (The Citizenry).
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"
REPORT_PATH = Path(__file__).parent.parent.parent / "reports" / "jan2026-ga4-top5-sessions-revenue.md"

GA4_BRANDS = ["ID", "BUR", "CZ"]
BRAND_NAMES = {"ID": "Interior Define", "BUR": "Burrow", "CZ": "The Citizenry"}

# January 2026 sale periods (EOY + Winter Refresh/Retreat + BUR Flash Sale)
# ID: Winter Refresh includes 1/14 (Sale Launch) through 1/28 (Final Hours)
# CZ: Winter Retreat includes 1/15 (PT Winter Refresh Sale send day)
# BUR: Flash Sale added 1/28–2/5
EOY_AND_YEAREND = [
    ("ID", "2026-01-01", "2026-01-06"),
    ("BUR", "2026-01-01", "2026-01-05"),
    ("CZ", "2026-01-01", "2026-01-04"),
]
WINTER_REFRESH_RETREAT = [
    ("ID", "2026-01-14", "2026-01-28"),   # incl. Sale Launch (1/14), Final Hours (1/28)
    ("BUR", "2026-01-15", "2026-01-27"),
    ("CZ", "2026-01-15", "2026-01-29"),  # incl. 1/15 PT Winter Refresh Sale
]
BUR_FLASH_SALE = [
    ("BUR", "2026-01-28", "2026-02-05"),
]


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


def is_during_sale(campaign: Dict[str, Any]) -> bool:
    brand = campaign.get("brand")
    if not brand:
        return False
    first_sent = (campaign.get("dates") or {}).get("first_sent")
    if not first_sent:
        return False
    d = parse_date(first_sent)
    if not d:
        return False
    for b, start, end in EOY_AND_YEAREND + WINTER_REFRESH_RETREAT + BUR_FLASH_SALE:
        if b == brand and date_in_range(d, start, end):
            return True
    return False


def load_jan2026_batch_email_ga4_brands() -> List[Dict[str, Any]]:
    campaigns = []
    for f in CAMPAIGNS_DIR.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(open(f))
        except Exception:
            continue
        if not data or data.get("channel") != "email":
            continue
        if data.get("braze_type") == "canvas_step":
            continue
        if data.get("brand") not in GA4_BRANDS:
            continue
        first_sent = (data.get("dates") or {}).get("first_sent")
        if not first_sent:
            continue
        d = parse_date(first_sent)
        if not d or d.year != 2026 or d.month != 1:
            continue
        perf = data.get("performance_summary", {})
        if not perf.get("total_sends") or perf["total_sends"] < 100:
            continue
        campaigns.append(data)
    return campaigns


def get_sessions(c: Dict[str, Any]) -> int:
    return int(((c.get("performance_summary") or {}).get("ga4") or {}).get("sessions") or 0)


def get_revenue(c: Dict[str, Any]) -> float:
    return float(((c.get("performance_summary") or {}).get("ga4") or {}).get("revenue") or 0)


def get_name(c: Dict[str, Any]) -> str:
    return (c.get("name") or "").strip()


def top5_sessions(campaigns: List[Dict]) -> List[Dict]:
    return sorted(campaigns, key=get_sessions, reverse=True)[:5]


def top5_revenue(campaigns: List[Dict]) -> List[Dict]:
    return sorted(campaigns, key=get_revenue, reverse=True)[:5]


# ID on-sale: combine End_of_Year_Sale_Final_Hours (01_06) + Emailify version into one row with asterisk
# Exclude "Designed_Version" so we only combine the two the user asked for.
def _is_eoy_final_hours_designed(c: Dict[str, Any]) -> bool:
    n = get_name(c)
    return "End_of_Year_Sale_Final_Hours" in n and "Emailify" not in n and "Designed_Version" not in n


def _is_eoy_final_hours_emailify(c: Dict[str, Any]) -> bool:
    n = get_name(c)
    return "Emailify" in n and ("EOY_Sale_Final_Hours" in n or "End_of_Year_Sale_Final_Hours" in n)


def id_on_sale_top5_revenue_rows(campaigns: List[Dict]) -> List[Any]:
    """Top 5 by revenue for ID on-sale, with EOY Final Hours (designed + Emailify) combined as one row."""
    designed = next((c for c in campaigns if _is_eoy_final_hours_designed(c) and not _is_eoy_final_hours_emailify(c)), None)
    emailify = next((c for c in campaigns if _is_eoy_final_hours_emailify(c)), None)
    rest = [c for c in campaigns if c != designed and c != emailify]
    rest_sorted = sorted(rest, key=get_revenue, reverse=True)
    rows = []
    if designed and emailify:
        combined = {
            "_combined": True,
            "name": "End of Year Sale Final Hours (designed + Emailify)*",
            "sessions": get_sessions(designed) + get_sessions(emailify),
            "revenue": get_revenue(designed) + get_revenue(emailify),
        }
        rows = rest_sorted[:4] + [combined]
    else:
        rows = rest_sorted[:5]
    rows = sorted(rows, key=lambda x: (x.get("revenue") if isinstance(x, dict) and "_combined" in x else get_revenue(x)), reverse=True)[:5]
    return rows


def id_off_sale_exclude_trade(campaigns: List[Dict]) -> List[Dict]:
    """Exclude TRADE emails from ID off-sale so we can show 5 non-TRADE campaigns."""
    return [c for c in campaigns if "TRADE" not in get_name(c)]


def main() -> None:
    campaigns = load_jan2026_batch_email_ga4_brands()
    on_sale = [c for c in campaigns if is_during_sale(c)]
    off_sale = [c for c in campaigns if not is_during_sale(c)]

    lines = [
        "# January 2026 — Top 5 Sessions & Top 5 Revenue by Brand (GA4)",
        "",
        "**Brands with GA4 data:** Interior Define (ID), Burrow (BUR), The Citizenry (CZ).",
        "",
        "**On-sale:** EOY Sale Extension / Year-End Refresh + Winter Refresh / Winter Retreat.",
        "**Off-sale:** All other days in January 2026.",
        "",
        "---",
        "",
    ]

    for brand in GA4_BRANDS:
        label = BRAND_NAMES[brand]
        on = [c for c in on_sale if c.get("brand") == brand]
        off = [c for c in off_sale if c.get("brand") == brand]
        if brand == "ID":
            off = id_off_sale_exclude_trade(off)

        lines.append(f"## {label} ({brand})")
        lines.append("")

        # On-sale
        lines.append("### On-sale period")
        lines.append("")
        lines.append("**Top 5 by sessions**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_sessions(on):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")
        lines.append("**Top 5 by revenue**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        if brand == "ID":
            id_revenue_rows = id_on_sale_top5_revenue_rows(on)
            for row in id_revenue_rows:
                if isinstance(row, dict) and row.get("_combined"):
                    lines.append(f"| {row['name']} | {row['sessions']:,} | {row['revenue']:,.2f} |")
                else:
                    lines.append(f"| {get_name(row)} | {get_sessions(row):,} | {get_revenue(row):,.2f} |")
            if any(isinstance(r, dict) and r.get("_combined") for r in id_revenue_rows):
                lines.append("")
                lines.append("* Numbers from designed and Emailify versions were combined.")
        else:
            for c in top5_revenue(on):
                lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")

        # Off-sale
        lines.append("### Off-sale period")
        lines.append("")
        lines.append("**Top 5 by sessions**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_sessions(off):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")
        lines.append("**Top 5 by revenue**")
        lines.append("")
        lines.append("| Campaign name | Sessions | Revenue ($) |")
        lines.append("|---------------|----------|--------------|")
        for c in top5_revenue(off):
            lines.append(f"| {get_name(c)} | {get_sessions(c):,} | {get_revenue(c):,.2f} |")
        lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Burrow Deliverability Overview by Receiver Domain
Replicates the Braze "Receiver Domain Breakdown (Top 100)" slide.

Usage:
    uv run python scripts/analysis/deliverability_by_domain.py
    uv run python scripts/analysis/deliverability_by_domain.py --start 2026-05-01 --end 2026-05-07
    uv run python scripts/analysis/deliverability_by_domain.py --start 2026-05-01 --end 2026-05-07 --limit 50
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR_APP_GROUP_ID = "67093a1f24ebbe0065cb9c77"


def build_query(start_date: str, end_date_exclusive: str, limit: int) -> str:
    # Each CTE aggregates independently by domain to avoid fan-out JOINs on DISPATCH_ID.
    return f"""
WITH sends AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT ID) AS sent
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
    GROUP BY 1
),
deliveries AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT ID) AS delivered
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_DELIVERY_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
    GROUP BY 1
),
soft_bounces AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT ID) AS soft_bounces
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
    GROUP BY 1
),
hard_bounces AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT ID) AS hard_bounces
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
    GROUP BY 1
),
opens AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS opens_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
      -- include machine opens to match Braze UI methodology
    GROUP BY 1
),
clicks AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS clicks_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
    GROUP BY 1
),
complaints AS (
    SELECT
        LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
        COUNT(DISTINCT ID) AS complaints
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_MARKASSPAM_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= '{start_date}'
      AND TO_TIMESTAMP(TIME) <  '{end_date_exclusive}'
    GROUP BY 1
)
SELECT
    s.domain                                                                            AS DOMAIN,
    s.sent                                                                              AS SENT,
    COALESCE(d.delivered,     0)                                                        AS DELIVERED,
    ROUND(COALESCE(d.delivered,     0) / NULLIF(s.sent, 0) * 100, 2)                   AS DELIVERY_RATE,
    COALESCE(sb.soft_bounces, 0)                                                        AS SOFT_BOUNCES,
    ROUND(COALESCE(sb.soft_bounces, 0) / NULLIF(s.sent, 0) * 100, 2)                   AS SOFT_BOUNCE_RATE,
    COALESCE(hb.hard_bounces, 0)                                                        AS HARD_BOUNCES,
    ROUND(COALESCE(hb.hard_bounces, 0) / NULLIF(s.sent, 0) * 100, 2)                   AS HARD_BOUNCE_RATE,
    COALESCE(o.opens_unique,  0)                                                        AS OPENS_UNIQUE,
    ROUND(COALESCE(o.opens_unique,  0) / NULLIF(s.sent, 0) * 100, 2)                   AS OPEN_UNIQUE_RATE,
    COALESCE(cl.clicks_unique, 0)                                                       AS CLICKS_UNIQUE,
    ROUND(COALESCE(cl.clicks_unique, 0) / NULLIF(s.sent, 0) * 100, 2)                  AS CLICKS_UNIQUE_RATE,
    COALESCE(c.complaints,    0)                                                        AS COMPLAINTS,
    ROUND(COALESCE(c.complaints,    0) / NULLIF(s.sent, 0) * 100, 4)                   AS COMPLAINT_RATE
FROM sends s
LEFT JOIN deliveries   d  ON s.domain = d.domain
LEFT JOIN soft_bounces sb ON s.domain = sb.domain
LEFT JOIN hard_bounces hb ON s.domain = hb.domain
LEFT JOIN opens        o  ON s.domain = o.domain
LEFT JOIN clicks       cl ON s.domain = cl.domain
LEFT JOIN complaints   c  ON s.domain = c.domain
ORDER BY s.sent DESC
LIMIT {limit}
"""


def color_cell(value: float, metric: str) -> str:
    """Return (bg, text) colors for a cell — flag outliers, reward clear winners."""
    if metric == "delivery_rate":
        if value >= 99:
            return "green"
        if value < 95:
            return "red"
        return "yellow"
    if metric == "open_rate":
        if value >= 20:
            return "green"
        return ""
    if metric == "hard_bounce_rate":
        if value > 0.5:
            return "red"
        if value > 0.1:
            return "yellow"
        return ""
    if metric == "complaint_rate":
        if value > 0.08:
            return "red"
        if value > 0.03:
            return "yellow"
        return ""
    return ""


COLORS = {
    "green":  {"bg": "#d4edda", "text": "#155724"},
    "yellow": {"bg": "#fff3cd", "text": "#856404"},
    "red":    {"bg": "#ea4335", "text": "#ffffff"},
}


def render_html(rows: list[dict], start_date: str, end_date: str, output_path: Path) -> None:
    # (label, data_key, color_metric_or_None)
    cols = [
        ("Receiver Domain", "DOMAIN",            None),
        ("Sent",            "SENT",              None),
        ("Delivered",       "DELIVERED",         None),
        ("Delivery Rate",   "DELIVERY_RATE",     "delivery_rate"),
        ("Soft Bounces",    "SOFT_BOUNCES",      None),
        ("Soft Bounce Rate","SOFT_BOUNCE_RATE",  None),
        ("Hard Bounces",    "HARD_BOUNCES",      None),
        ("Hard Bounce Rate","HARD_BOUNCE_RATE",  "hard_bounce_rate"),
        ("Opens Unique",    "OPENS_UNIQUE",      None),
        ("Open Unique Rate","OPEN_UNIQUE_RATE",  "open_rate"),
        ("Clicks Unique",   "CLICKS_UNIQUE",     None),
        ("Clicks Unique Rate","CLICKS_UNIQUE_RATE", None),
        ("Complaints",      "COMPLAINTS",        None),
        ("Complaint Rate",  "COMPLAINT_RATE",    "complaint_rate"),
    ]

    header_html = "".join(f"<th>{label}</th>" for label, _key, _metric in cols)

    body_rows = []
    for i, row in enumerate(rows, 1):
        cells = [f"<td>{i}</td>"]
        for label, key, metric in cols:
            val = row.get(key, 0) or 0
            color_key = color_cell(float(val), metric) if metric else ""
            if color_key:
                c = COLORS[color_key]
                style = f' style="background:{c["bg"]};color:{c["text"]};font-weight:600"'
            else:
                style = ""
            is_rate = "RATE" in key
            display = f"{val}%" if is_rate else (f"{int(val):,}" if key != "DOMAIN" else str(val))
            cells.append(f"<td{style}>{display}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    body_html = "\n".join(body_rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Burrow Deliverability Overview — {start_date} to {end_date}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; background: #f8f8f8; }}
  h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
  .brand {{ font-style: italic; color: #888; font-size: 18px; }}
  .subtitle {{ font-size: 14px; color: #666; margin-bottom: 24px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 13px; }}
  th {{ background: #f4f4f4; border: 1px solid #e0e0e0; padding: 8px 10px; text-align: left; font-weight: 600; white-space: nowrap; font-size: 12px; }}
  td {{ border: 1px solid #e8e8e8; padding: 7px 10px; white-space: nowrap; }}
  tr:hover td {{ background: #fafafa; }}
  tr:nth-child(even) td {{ background: #fdfdfb; }}
</style>
</head>
<body>
<h1>Burrow Deliverability Overview <span class="brand">braze</span></h1>
<div class="subtitle">Receiver Domain Breakdown (Top {len(rows)}) &nbsp;·&nbsp; {start_date} – {end_date}</div>
<table>
  <thead><tr><th>#</th>{header_html}</tr></thead>
  <tbody>{body_html}</tbody>
</table>
</body>
</html>"""

    output_path.write_text(html)
    print(f"\nHTML report saved → {output_path}")


def print_table(rows: list[dict]) -> None:
    cols = [
        ("Domain",  "DOMAIN",             20),
        ("Sent",    "SENT",               10),
        ("Delivered","DELIVERED",         10),
        ("Del%",    "DELIVERY_RATE",       7),
        ("SftBnc",  "SOFT_BOUNCES",        7),
        ("SftBnc%", "SOFT_BOUNCE_RATE",    8),
        ("HrdBnc",  "HARD_BOUNCES",        7),
        ("HrdBnc%", "HARD_BOUNCE_RATE",    8),
        ("Opens",   "OPENS_UNIQUE",        8),
        ("Open%",   "OPEN_UNIQUE_RATE",    7),
        ("Clicks",  "CLICKS_UNIQUE",       7),
        ("Clk%",    "CLICKS_UNIQUE_RATE",  6),
        ("Compl.",  "COMPLAINTS",          7),
        ("Compl%",  "COMPLAINT_RATE",      7),
    ]
    header = "  ".join(label.ljust(w) for label, _, w in cols)
    print("\n" + header)
    print("-" * len(header))
    for i, row in enumerate(rows, 1):
        parts = []
        for label, key, w in cols:
            val = row.get(key, 0) or 0
            if "RATE" in key:
                parts.append(f"{val}%".ljust(w))
            elif key in ("SENT", "DELIVERED", "OPENS_UNIQUE", "CLICKS_UNIQUE"):
                parts.append(f"{int(val):,}".ljust(w))
            else:
                parts.append(str(val).ljust(w))
        print("  ".join(parts))


def main():
    parser = argparse.ArgumentParser(description="Burrow deliverability breakdown by receiver domain")
    parser.add_argument("--start",  default="2026-05-01", help="Start date inclusive (YYYY-MM-DD)")
    parser.add_argument("--end",    default="2026-05-07", help="End date inclusive (YYYY-MM-DD)")
    parser.add_argument("--limit",  default=100, type=int, help="Max domains to return (default 100)")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML report")
    args = parser.parse_args()

    # End date is inclusive in the CLI but exclusive in SQL
    from datetime import date, timedelta
    end_exclusive = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()

    print(f"Querying Burrow deliverability by domain: {args.start} – {args.end} …")

    client = get_snowflake_client(schema=SCHEMA, database=DB)
    query = build_query(args.start, end_exclusive, args.limit)
    rows = client.execute_query(query)

    if not rows:
        print("No data returned.")
        return

    print(f"\nReceiver Domain Breakdown — Top {len(rows)} domains by volume\n")
    print_table(rows)

    if not args.no_html:
        out_dir = Path(__file__).parent.parent.parent / "reports"
        out_dir.mkdir(exist_ok=True)
        fname = f"deliverability_by_domain_BUR_{args.start}_{args.end}.html"
        render_html(rows, args.start, args.end, out_dir / fname)


if __name__ == "__main__":
    main()

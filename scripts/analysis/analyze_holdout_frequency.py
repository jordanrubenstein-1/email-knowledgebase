#!/usr/bin/env python3
"""
Holdout Frequency Test — Refreshed Results
==========================================
Replicates the Braze Query Builder queries used for the BW and HAV PC holdout
frequency tests, running them against the Braze raw events datashare in Snowflake.

Test window: Jan 14, 2026 – today
Brands covered by datashare: BW (Burrow), HAV PC (Havenly Pre-Converted)
ID (Interior Define): not in datashare — script prints updated QB SQL instead.

Usage:
    # BW + HAV PC only (Snowflake):
    uv run python scripts/analysis/analyze_holdout_frequency.py

    # All three brands (pass ID QB export):
    uv run python scripts/analysis/analyze_holdout_frequency.py \\
      --id-csv ~/Downloads/"Holdout Test - knowledgebase version - March 6, 2026 at 10_38 AM.csv"
"""

import sys
import csv
import argparse
from pathlib import Path
from datetime import date, datetime, timezone

import math

# Scipy norm for p-value calculation
try:
    from scipy.stats import norm as _norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

sys.path.insert(0, str(Path(__file__).parent.parent))
from snowflake_client import get_snowflake_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"

START_TS = 1768348800  # 2026-01-14 00:00:00 UTC

# ---------------------------------------------------------------------------
# Baseline — hardcoded 2/28 numbers for "Changes from Previous Report"
# ---------------------------------------------------------------------------

BASELINE_228 = {
    "BW": {
        "purchase_rate_ctrl":       0.00190,
        "purchase_rate_hold":       0.00144,
        "delta_purchase_pct":       -24.2,
        "p_purchase":               0.032,
        "sig_purchase":             True,
        "revenue_per_user_ctrl":    2.63,
        "revenue_per_user_hold":    1.97,
        "delta_rev_pct":            -25.1,
        "swatch_rate_ctrl":         None,   # not in 2/28 doc at this level
        "swatch_rate_hold":         None,
        "sends_per_user_ctrl":      None,
        "sends_per_user_hold":      None,
    },
    "HAV": {
        "conv_rate_ctrl":           0.00163,
        "conv_rate_hold":           0.00355,
        "delta_conv_pct":           118.3,
        "p_conv":                   0.0001,
        "sig_conv":                 True,
        "clicker_rate_ctrl":        0.0476,
        "clicker_rate_hold":        0.0549,
        "delta_click_pct":          15.3,
        "sends_per_user_ctrl":      31.71,
        "sends_per_user_hold":      26.30,
    },
    "ID": {
        "purchase_rate_ctrl":       0.00396,
        "purchase_rate_hold":       0.00578,
        "delta_purchase_pct":       46.1,
        "p_purchase":               0.00006,
        "sig_purchase":             True,
        "swatch_rate_ctrl":         0.01002,
        "swatch_rate_hold":         0.03225,
        "delta_swatch_pct":         221.0,
        "revenue_per_user_ctrl":    13.10,
        "revenue_per_user_hold":    16.22,
        "delta_rev_pct":            23.8,
    },
}

BRAND_CONFIG = {
    "BW": {
        "label": "Burrow",
        "app_group_id": "67093a1f24ebbe0065cb9c77",
        "cohort_all":   "72021eaf-ec49-49e3-9e92-a544d71a4af4",  # sent to everyone
        "cohort_ctrl":  "178c8cbe-50b5-4121-8e8f-c36d8ac48ad0",  # sent to control only
        "swatch_event": "Swatch Order Completed",
    },
    "HAV": {
        "label": "Havenly Pre-Converted",
        "app_group_id": "664223fb71bcf3005760dfc2",
        "cohort_all":   "fa2b2b27-b3b7-4a25-915a-e22748d6edce",
        "cohort_ctrl":  "ee0ef3d3-1aa6-4c0c-b75b-7d625d331e78",
        "design_fee_campaign": "31ad305f-931b-a73b-e338-2c836bdcac37",
    },
}

# ID is not in the datashare — we print updated QB SQL for manual use
ID_COHORT_ALL  = "c84bd218-be71-4e6a-93ab-ccad6fb8c05e"
ID_COHORT_CTRL = "37818393-6659-4d83-8bb1-fe3dd5e4b42f"


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def cohort_cte(cfg: dict, db: str, schema: str) -> str:
    """Return the WITH cohort AS (...) clause for a brand."""
    return f"""
WITH cohort AS (
  SELECT
    a.user_id,
    CASE WHEN b.user_id IS NOT NULL THEN 'control' ELSE 'holdout' END AS test_group
  FROM (
    SELECT DISTINCT user_id
    FROM {db}.{schema}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{cfg["cohort_all"]}'
      AND app_group_id = '{cfg["app_group_id"]}'
  ) a
  LEFT JOIN (
    SELECT DISTINCT user_id
    FROM {db}.{schema}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{cfg["cohort_ctrl"]}'
      AND app_group_id = '{cfg["app_group_id"]}'
  ) b ON a.user_id = b.user_id
)"""


def current_end_ts() -> int:
    """Unix timestamp for right now (UTC)."""
    return int(datetime.now(timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# BW: purchase + swatch
# ---------------------------------------------------------------------------

def query_bw(client, cfg: dict) -> list[dict]:
    end_ts = current_end_ts()
    sql = cohort_cte(cfg, DB, SCHEMA) + f"""
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                              AS users,
  COUNT(DISTINCT pur.user_id)                                                 AS purchasers,
  COALESCE(SUM(pur.purchase_events), 0)                                       AS total_purchase_events,
  COALESCE(SUM(pur.revenue), 0)                                               AS total_revenue,
  COALESCE(SUM(pur.revenue), 0)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS revenue_per_user,
  COALESCE(SUM(pur.revenue), 0)
    / NULLIF(SUM(pur.purchase_events), 0)                                     AS average_order_value,
  CAST(COUNT(DISTINCT pur.user_id) AS FLOAT)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS purchase_rate,
  COUNT(DISTINCT sw.user_id)                                                  AS swatch_converters,
  CAST(COUNT(DISTINCT sw.user_id) AS FLOAT)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS swatch_conversion_rate
FROM cohort
LEFT JOIN (
  SELECT user_id, COUNT(*) AS purchase_events, SUM(COALESCE(price, 0)) AS revenue
  FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) pur ON pur.user_id = cohort.user_id
LEFT JOIN (
  SELECT DISTINCT user_id
  FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND name = '{cfg["swatch_event"]}'
    AND time >= {START_TS} AND time < {end_ts}
) sw ON sw.user_id = cohort.user_id
GROUP BY cohort.test_group
ORDER BY cohort.test_group
"""
    return client.execute_query(sql)


# ---------------------------------------------------------------------------
# BW: send frequency (email + SMS)
# ---------------------------------------------------------------------------

def query_bw_sends(client, cfg: dict) -> list[dict]:
    end_ts = current_end_ts()
    sql = cohort_cte(cfg, DB, SCHEMA) + f"""
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                               AS users,
  COALESCE(SUM(sends.total_sends), 0)                                          AS total_sends,
  ROUND(SUM(sends.total_sends)::FLOAT / COUNT(DISTINCT cohort.user_id), 2)    AS sends_per_user,
  ROUND(SUM(sends.email_sends)::FLOAT / COUNT(DISTINCT cohort.user_id), 2)    AS email_sends_per_user,
  ROUND(SUM(sends.sms_sends)::FLOAT / COUNT(DISTINCT cohort.user_id), 2)      AS sms_sends_per_user
FROM cohort
LEFT JOIN (
  SELECT user_id,
    COUNT(*) AS total_sends,
    SUM(CASE WHEN channel = 'email' THEN 1 ELSE 0 END) AS email_sends,
    SUM(CASE WHEN channel = 'sms'   THEN 1 ELSE 0 END) AS sms_sends
  FROM (
    SELECT user_id, 'email' AS channel
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE app_group_id = '{cfg["app_group_id"]}'
      AND time >= {START_TS} AND time < {end_ts}
    UNION ALL
    SELECT user_id, 'sms' AS channel
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
    WHERE app_group_id = '{cfg["app_group_id"]}'
      AND time >= {START_TS} AND time < {end_ts}
  ) allsends
  GROUP BY user_id
) sends ON sends.user_id = cohort.user_id
GROUP BY cohort.test_group
ORDER BY cohort.test_group
"""
    return client.execute_query(sql)


# ---------------------------------------------------------------------------
# HAV: conversion (design fee proxy)
# ---------------------------------------------------------------------------

def query_hav_conversion(client, cfg: dict) -> list[dict]:
    end_ts = current_end_ts()
    sql = cohort_cte(cfg, DB, SCHEMA) + f"""
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                              AS users,
  COUNT(DISTINCT conv.user_id)                                                AS converters,
  COALESCE(SUM(conv.conv_sends), 0)                                           AS total_design_fee_proxy_events,
  CAST(COUNT(DISTINCT conv.user_id) AS FLOAT)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS conversion_rate
FROM cohort
LEFT JOIN (
  SELECT user_id, COUNT(*) AS conv_sends
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND campaign_api_id = '{cfg["design_fee_campaign"]}'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) conv ON conv.user_id = cohort.user_id
GROUP BY cohort.test_group
ORDER BY cohort.test_group
"""
    return client.execute_query(sql)


# ---------------------------------------------------------------------------
# HAV: engagement (sends / clicks / opens / AI)
# ---------------------------------------------------------------------------

def query_hav_engagement(client, cfg: dict) -> list[dict]:
    end_ts = current_end_ts()
    sql = cohort_cte(cfg, DB, SCHEMA) + f"""
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                              AS users,
  COALESCE(SUM(sends.total_sends), 0)                                         AS total_sends,
  ROUND(SUM(sends.total_sends)::FLOAT / COUNT(DISTINCT cohort.user_id), 2)   AS sends_per_user,
  COALESCE(SUM(clicks.total_clicks), 0)                                       AS total_clicks,
  ROUND(SUM(clicks.total_clicks)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS clicks_per_user,
  COALESCE(SUM(clicks.unique_clicks), 0)                                      AS unique_clicks,
  ROUND(SUM(clicks.unique_clicks)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS unique_clicks_per_user,
  COUNT(DISTINCT clicks.user_id)                                              AS unique_clickers,
  ROUND(COUNT(DISTINCT clicks.user_id)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS clicker_rate,
  COALESCE(SUM(opens.total_opens), 0)                                         AS total_opens,
  ROUND(SUM(opens.total_opens)::FLOAT / COUNT(DISTINCT cohort.user_id), 4)   AS opens_per_user,
  COUNT(DISTINCT explore_ai.user_id)                                          AS explore_ai_users,
  COALESCE(SUM(explore_ai.event_count), 0)                                    AS explore_ai_total_events,
  ROUND(COUNT(DISTINCT explore_ai.user_id)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS explore_ai_rate,
  ROUND(SUM(explore_ai.event_count)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS explore_ai_per_user,
  COUNT(DISTINCT ai_session.user_id)                                          AS ai_session_users,
  COALESCE(SUM(ai_session.event_count), 0)                                    AS ai_session_total_events,
  ROUND(COUNT(DISTINCT ai_session.user_id)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS ai_session_rate,
  ROUND(SUM(ai_session.event_count)::FLOAT / COUNT(DISTINCT cohort.user_id), 4) AS ai_session_per_user
FROM cohort
LEFT JOIN (
  SELECT user_id, COUNT(*) AS total_sends
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) sends ON sends.user_id = cohort.user_id
LEFT JOIN (
  SELECT user_id, COUNT(*) AS total_clicks, COUNT(DISTINCT dispatch_id) AS unique_clicks
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) clicks ON clicks.user_id = cohort.user_id
LEFT JOIN (
  SELECT user_id, COUNT(*) AS total_opens
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) opens ON opens.user_id = cohort.user_id
LEFT JOIN (
  SELECT user_id, COUNT(*) AS event_count
  FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND name = 'explore_with_ai'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) explore_ai ON explore_ai.user_id = cohort.user_id
LEFT JOIN (
  SELECT user_id, COUNT(*) AS event_count
  FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
  WHERE app_group_id = '{cfg["app_group_id"]}'
    AND name = 'AI Design Session Started FE'
    AND time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) ai_session ON ai_session.user_id = cohort.user_id
GROUP BY cohort.test_group
ORDER BY cohort.test_group
"""
    return client.execute_query(sql)


# ---------------------------------------------------------------------------
# Statistical significance (z-test for proportions)
# ---------------------------------------------------------------------------

def sig_test(n_ctrl: int, conv_ctrl: int, n_hold: int, conv_hold: int) -> tuple:
    """Z-test for two proportions. Returns (z_stat, p_value, significant_at_95)."""
    if n_ctrl == 0 or n_hold == 0:
        return None, None, None
    p1 = conv_ctrl / n_ctrl
    p2 = conv_hold / n_hold
    p_pool = (conv_ctrl + conv_hold) / (n_ctrl + n_hold)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_ctrl + 1 / n_hold))
    if se == 0:
        return None, None, None
    z = (p1 - p2) / se
    if HAS_SCIPY:
        p = float(2 * _norm.sf(abs(z)))
    else:
        # Approximate p-value without scipy using error function
        p = float(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))))
    return round(z, 2), round(p, 5), p < 0.05


def delta_pct(holdout_rate: float, control_rate: float) -> str:
    if control_rate == 0:
        return "—"
    d = (holdout_rate - control_rate) / control_rate * 100
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.1f}%"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def fmt_pct(v: float) -> str:
    return f"{v * 100:.3f}%"

def fmt_money(v: float) -> str:
    return f"${v:,.2f}"

def fmt_num(v) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"

def row_to_dict(rows: list[dict]) -> dict[str, dict]:
    """Index result rows by test_group value."""
    out = {}
    for r in rows:
        key = str(r.get("TEST_GROUP") or r.get("test_group", "")).lower()
        # Normalize keys to lowercase
        out[key] = {k.lower(): v for k, v in r.items()}
    return out


def print_section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_table(headers: list[str], rows: list[list]):
    col_widths = [max(len(str(headers[i])), max(len(str(r[i])) for r in rows)) for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*row))


def print_sig_table(entries: list[tuple]):
    """entries: list of (brand, metric, z, p, significant, direction)"""
    if not HAS_SCIPY:
        print("\n  (scipy not installed — significance tests skipped)")
        return
    headers = ["Brand", "Metric", "z-stat", "p-value", "Sig (95%)?", "Direction"]
    rows = []
    for brand, metric, z, p, sig, direction in entries:
        rows.append([
            brand, metric,
            f"{z:.2f}" if z is not None else "—",
            f"{p:.5f}" if p is not None else "—",
            "YES" if sig else "NO",
            direction,
        ])
    print_table(headers, rows)


# ---------------------------------------------------------------------------
# ID: print updated QB SQL for manual use
# ---------------------------------------------------------------------------

def print_id_qb_sql():
    end_ts = current_end_ts()
    today = date.today().isoformat()
    print_section(f"Interior Define — Braze Query Builder SQL (updated through {today})")
    print(f"""
NOTE: ID is not in the Snowflake datashare. Paste the queries below into
Braze Query Builder to get refreshed results.

End timestamp used: {end_ts}  ({today} ~now UTC)

--- Query 1: Purchase + Swatch ---
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                              AS users,
  COUNT(DISTINCT pur.user_id)                                                 AS purchasers,
  COALESCE(SUM(pur.purchase_events), 0)                                       AS total_purchase_events,
  COALESCE(SUM(pur.revenue), 0)                                               AS total_revenue,
  COALESCE(SUM(pur.revenue), 0) / NULLIF(COUNT(DISTINCT cohort.user_id), 0)  AS revenue_per_user,
  COALESCE(SUM(pur.revenue), 0) / NULLIF(SUM(pur.purchase_events), 0)        AS average_order_value,
  CAST(COUNT(DISTINCT pur.user_id) AS FLOAT)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS purchase_rate,
  COUNT(DISTINCT sw.user_id)                                                  AS swatch_converters,
  CAST(COUNT(DISTINCT sw.user_id) AS FLOAT)
    / NULLIF(COUNT(DISTINCT cohort.user_id), 0)                               AS swatch_conversion_rate
FROM (
  SELECT a.user_id,
    CASE WHEN b.user_id IS NOT NULL THEN 'control' ELSE 'holdout' END AS test_group
  FROM (
    SELECT DISTINCT user_id FROM USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{ID_COHORT_ALL}'
  ) a
  LEFT JOIN (
    SELECT DISTINCT user_id FROM USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{ID_COHORT_CTRL}'
  ) b ON a.user_id = b.user_id
) cohort
LEFT JOIN (
  SELECT user_id, COUNT(*) AS purchase_events, SUM(COALESCE(price, 0)) AS revenue
  FROM USERS_BEHAVIORS_PURCHASE_SHARED
  WHERE time >= {START_TS} AND time < {end_ts}
  GROUP BY user_id
) pur ON pur.user_id = cohort.user_id
LEFT JOIN (
  SELECT DISTINCT user_id
  FROM USERS_BEHAVIORS_CUSTOMEVENT_SHARED
  WHERE name = 'Swatch Order'
    AND time >= {START_TS} AND time < {end_ts}
) sw ON sw.user_id = cohort.user_id
GROUP BY cohort.test_group
ORDER BY cohort.test_group;

--- Query 2: Sends/User ---
SELECT
  cohort.test_group,
  COUNT(DISTINCT cohort.user_id)                                              AS users,
  COUNT(s.id)                                                                 AS total_sends,
  ROUND(COUNT(s.id)::FLOAT / COUNT(DISTINCT cohort.user_id), 2)              AS sends_per_user
FROM (
  SELECT a.user_id,
    CASE WHEN b.user_id IS NOT NULL THEN 'control' ELSE 'holdout' END AS test_group
  FROM (
    SELECT DISTINCT user_id FROM USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{ID_COHORT_ALL}'
  ) a
  LEFT JOIN (
    SELECT DISTINCT user_id FROM USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE campaign_api_id = '{ID_COHORT_CTRL}'
  ) b ON a.user_id = b.user_id
) cohort
LEFT JOIN USERS_MESSAGES_EMAIL_SEND_SHARED s
  ON s.user_id = cohort.user_id
  AND s.time >= {START_TS} AND s.time < {end_ts}
GROUP BY cohort.test_group
ORDER BY cohort.test_group;
""")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def save_csv(rows_by_section: dict[str, list[dict]], output_path: Path):
    """Save all results to a flat CSV with brand/section columns."""
    with open(output_path, "w", newline="") as f:
        writer = None
        for section, rows in rows_by_section.items():
            for row in rows:
                row_with_section = {"section": section, **row}
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(row_with_section.keys()))
                    writer.writeheader()
                writer.writerow(row_with_section)
    print(f"\nSaved: {output_path}")


# ---------------------------------------------------------------------------
# ID: load QB CSV export
# ---------------------------------------------------------------------------

def load_id_csv(path: str) -> list[dict]:
    """Read the ID Query Builder export CSV and normalize keys to lowercase."""
    rows = []
    with open(Path(path).expanduser(), newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.lower(): _coerce(v) for k, v in row.items()})
    return rows


def _coerce(v: str):
    """Try to convert a CSV string to int or float, else return as-is."""
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------

def _trend(old, new, higher_is_better=True):
    """Return a trend label comparing new vs old."""
    if old is None or new is None:
        return "—"
    if abs(new - old) < 0.001 * abs(old + 1e-9):
        return "Stable"
    improving = (new > old) if higher_is_better else (new < old)
    return "Improving ✓" if improving else "Narrowing"


def _pct_fmt(v, decimals=1):
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def _money_fmt(v):
    if v is None:
        return "—"
    return f"${v:,.2f}"


def generate_markdown_report(results: dict, today: str) -> str:
    """
    Build a full 7-section markdown report matching the 2/28 Word doc structure.

    results dict expected keys:
        bw:       {'ctrl': dict, 'hold': dict}
        hav_conv: {'ctrl': dict, 'hold': dict}
        hav_eng:  {'ctrl': dict, 'hold': dict}
        id:       {'ctrl': dict, 'hold': dict}  (optional)
        sig_entries: list of (brand, metric, z, p, sig, direction)
    """
    lines = []
    sig_entries = results.get("sig_entries", [])

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "# Email Holdout Test Analysis",
        "",
        f"**Test Period:** January 14, 2026 – {today}  ",
        "**Brands:** Burrow (BW), Havenly Pre-Converted (HAV PC), Interior Define (ID)  ",
        "**Data Sources:** Burrow & HAV — Braze Raw Events Datashare (Snowflake); ID — Braze Query Builder export  ",
        "",
    ]

    # ── Section 1: Test Design ────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## 1. Test Design",
        "",
        "The holdout frequency test splits each brand's email list into two groups. "
        "The **control group** receives the full email cadence (all campaigns, same as before the test). "
        "The **holdout group** is excluded from certain sends, resulting in a lower send frequency. "
        "The cohorts are defined using two Braze campaign API IDs per brand: one campaign sent to "
        "the entire test universe (establishing cohort membership) and one sent exclusively to the "
        "control group (distinguishing control from holdout). No manual segment uploads are required — "
        "cohort membership is derived entirely from send events in the Braze raw events datashare.",
        "",
        "The test launched **January 14, 2026** and remains live. "
        "Results are cumulative from the test start through today's date.",
        "",
    ]

    # ── Section 2: Send Frequency ─────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## 2. Send Frequency",
        "",
        "Send frequency is measured as total emails sent per user within the test window.",
        "",
    ]

    # Brand data references (HAV/ID first — winning with significance; BW last)
    bw_d = results.get("bw")
    bw_send_d = results.get("bw_sends")
    hav_conv_d = results.get("hav_conv")
    hav_eng_d = results.get("hav_eng")
    id_d = results.get("id")

    freq_rows = []
    if hav_eng_d:
        c, h = hav_eng_d["ctrl"], hav_eng_d["hold"]
        spuc = c.get("sends_per_user", 0) or 0
        spuh = h.get("sends_per_user", 0) or 0
        red = delta_pct(spuh, spuc) if spuc else "—"
        freq_rows.append(("HAV PC", f"{spuc:.2f}", f"{spuh:.2f}", red, ""))
    id_send_d = results.get("id_sends")
    if id_d or id_send_d:
        if id_send_d:
            spuc = id_send_d["ctrl"]
            spuh = id_send_d["hold"]
            red = delta_pct(spuh, spuc) if spuc else "—"
            freq_rows.append(("Interior Define (ID)", f"{spuc:.2f}", f"{spuh:.2f}", red, "*(email only)*"))
        else:
            freq_rows.append(("Interior Define (ID)", "—", "—", "—", "*(sends/user not in QB export)*"))
    if bw_d or bw_send_d:
        if bw_send_d:
            c, h = bw_send_d["ctrl"], bw_send_d["hold"]
            spuc = c.get("sends_per_user", 0) or 0
            spuh = h.get("sends_per_user", 0) or 0
            red = delta_pct(spuh, spuc) if spuc else "—"
            freq_rows.append(("Burrow (BW)", f"{spuc:.2f}", f"{spuh:.2f}", red, "*(email + SMS)*"))
        else:
            freq_rows.append(("Burrow (BW)", "—", "—", "—", "*(sends/user not available)*"))

    if freq_rows:
        lines.append("| Brand | Control Sends/User | Holdout Sends/User | Reduction | Notes |")
        lines.append("|-------|-------------------|-------------------|-----------|-------|")
        for brand, ctrl_s, hold_s, red, notes in freq_rows:
            lines.append(f"| {brand} | {ctrl_s} | {hold_s} | {red} | {notes} |")
        lines.append("")

    # ── Section 3: Performance Results ───────────────────────────────────────
    lines += [
        "---",
        "",
        "## 3. Performance Results",
        "",
    ]

    # HAV Conversion
    if hav_conv_d:
        c, h = hav_conv_d["ctrl"], hav_conv_d["hold"]
        lines += [
            "### 3a. Havenly Pre-Converted (HAV PC) — Conversion",
            "",
            "| Metric | Control | Holdout | Delta |",
            "|--------|---------|---------|-------|",
            f"| Users | {fmt_num(c['users'])} | {fmt_num(h['users'])} | — |",
            f"| Converters | {fmt_num(c['converters'])} | {fmt_num(h['converters'])} | — |",
            f"| Conversion Rate | {fmt_pct(c['conversion_rate'])} | {fmt_pct(h['conversion_rate'])} | {delta_pct(h['conversion_rate'], c['conversion_rate'])} |",
            f"| Design Fee Events | {fmt_num(c['total_design_fee_proxy_events'])} | {fmt_num(h['total_design_fee_proxy_events'])} | — |",
            "",
        ]

    # HAV Engagement
    if hav_eng_d:
        c, h = hav_eng_d["ctrl"], hav_eng_d["hold"]
        lines += [
            "### 3b. Havenly Pre-Converted (HAV PC) — Email Engagement",
            "",
            "| Metric | Control | Holdout | Delta |",
            "|--------|---------|---------|-------|",
            f"| Users | {fmt_num(c['users'])} | {fmt_num(h['users'])} | — |",
            f"| Sends/User | {c['sends_per_user']:.2f} | {h['sends_per_user']:.2f} | {delta_pct(h['sends_per_user'], c['sends_per_user'])} |",
            f"| Clicks/User | {c['clicks_per_user']:.4f} | {h['clicks_per_user']:.4f} | {delta_pct(h['clicks_per_user'], c['clicks_per_user'])} |",
            f"| Unique Clicks/User | {c['unique_clicks_per_user']:.4f} | {h['unique_clicks_per_user']:.4f} | {delta_pct(h['unique_clicks_per_user'], c['unique_clicks_per_user'])} |",
            f"| Clicker Rate | {fmt_pct(c['clicker_rate'])} | {fmt_pct(h['clicker_rate'])} | {delta_pct(h['clicker_rate'], c['clicker_rate'])} |",
            f"| Opens/User | {c['opens_per_user']:.4f} | {h['opens_per_user']:.4f} | {delta_pct(h['opens_per_user'], c['opens_per_user'])} |",
            "",
            "### 3c. Havenly Pre-Converted (HAV PC) — AI Feature Engagement",
            "",
            "| Metric | Control | Holdout | Delta |",
            "|--------|---------|---------|-------|",
            f"| Explore AI Users | {fmt_num(c['explore_ai_users'])} | {fmt_num(h['explore_ai_users'])} | — |",
            f"| **Explore AI Rate** | **{fmt_pct(c['explore_ai_rate'])}** | **{fmt_pct(h['explore_ai_rate'])}** | **{delta_pct(h['explore_ai_rate'], c['explore_ai_rate'])}** |",
            f"| Explore AI Events/User | {c['explore_ai_per_user']:.4f} | {h['explore_ai_per_user']:.4f} | — |",
            f"| AI Session Users | {fmt_num(c['ai_session_users'])} | {fmt_num(h['ai_session_users'])} | — |",
            f"| AI Session Rate | {fmt_pct(c['ai_session_rate'])} | {fmt_pct(h['ai_session_rate'])} | {delta_pct(h['ai_session_rate'], c['ai_session_rate'])} |",
            f"| AI Session Events/User | {c['ai_session_per_user']:.4f} | {h['ai_session_per_user']:.4f} | — |",
            "",
        ]

    # ID
    if id_d:
        c, h = id_d["ctrl"], id_d["hold"]
        lines += [
            "### 3d. Interior Define (ID) — Purchase & Revenue *(from QB export)*",
            "",
            "| Metric | Control | Holdout | Delta |",
            "|--------|---------|---------|-------|",
            f"| Users | {fmt_num(c['users'])} | {fmt_num(h['users'])} | — |",
            f"| Purchasers | {fmt_num(c['purchasers'])} | {fmt_num(h['purchasers'])} | — |",
            f"| Purchase Rate | {fmt_pct(c['purchase_rate'])} | {fmt_pct(h['purchase_rate'])} | {delta_pct(h['purchase_rate'], c['purchase_rate'])} |",
            f"| Total Revenue | {fmt_money(c['total_revenue'])} | {fmt_money(h['total_revenue'])} | — |",
            f"| Revenue/User | {fmt_money(c['revenue_per_user'])} | {fmt_money(h['revenue_per_user'])} | {delta_pct(h['revenue_per_user'], c['revenue_per_user'])} |",
            f"| Avg Order Value | {fmt_money(c['average_order_value'] or 0)} | {fmt_money(h['average_order_value'] or 0)} | {delta_pct(h['average_order_value'] or 0, c['average_order_value'] or 0)} |",
            f"| Swatch Converters | {fmt_num(c['swatch_converters'])} | {fmt_num(h['swatch_converters'])} | — |",
            f"| Swatch Conv Rate | {fmt_pct(c['swatch_conversion_rate'])} | {fmt_pct(h['swatch_conversion_rate'])} | {delta_pct(h['swatch_conversion_rate'], c['swatch_conversion_rate'])} |",
            "",
        ]

    # BW
    if bw_d:
        c, h = bw_d["ctrl"], bw_d["hold"]
        lines += [
            "### 3e. Burrow (BW)",
            "",
            "| Metric | Control | Holdout | Delta |",
            "|--------|---------|---------|-------|",
            f"| Users | {fmt_num(c['users'])} | {fmt_num(h['users'])} | — |",
            f"| Purchasers | {fmt_num(c['purchasers'])} | {fmt_num(h['purchasers'])} | — |",
            f"| Purchase Rate | {fmt_pct(c['purchase_rate'])} | {fmt_pct(h['purchase_rate'])} | {delta_pct(h['purchase_rate'], c['purchase_rate'])} |",
            f"| Total Revenue | {fmt_money(c['total_revenue'])} | {fmt_money(h['total_revenue'])} | — |",
            f"| Revenue/User | {fmt_money(c['revenue_per_user'])} | {fmt_money(h['revenue_per_user'])} | {delta_pct(h['revenue_per_user'], c['revenue_per_user'])} |",
            f"| Avg Order Value | {fmt_money(c['average_order_value'] or 0)} | {fmt_money(h['average_order_value'] or 0)} | {delta_pct(h['average_order_value'] or 0, c['average_order_value'] or 0)} |",
            f"| Swatch Converters | {fmt_num(c['swatch_converters'])} | {fmt_num(h['swatch_converters'])} | — |",
            f"| Swatch Conv Rate | {fmt_pct(c['swatch_conversion_rate'])} | {fmt_pct(h['swatch_conversion_rate'])} | {delta_pct(h['swatch_conversion_rate'], c['swatch_conversion_rate'])} |",
            "",
        ]

    # ── Section 4: Statistical Significance ──────────────────────────────────
    lines += [
        "---",
        "",
        "## 4. Statistical Significance",
        "",
        "Z-test for two proportions (two-tailed, α = 0.05).",
        "",
        "| Brand | Metric | z-stat | p-value | Sig (95%)? | Direction |",
        "|-------|--------|--------|---------|------------|-----------|",
    ]
    for brand, metric, z, p, sig, direction in sig_entries:
        z_s = f"{z:.2f}" if z is not None else "—"
        p_s = f"{p:.5f}" if p is not None else "—"
        sig_s = "**YES ✓**" if sig else "NO"
        lines.append(f"| {brand} | {metric} | {z_s} | {p_s} | {sig_s} | {direction} |")
    lines.append("")

    # ── Section 5: Incremental Impact Analysis ────────────────────────────────
    lines += [
        "---",
        "",
        "## 5. Incremental Impact Analysis",
        "",
    ]

    # HAV: holdout outperforms → email is suppressing conversions
    if hav_conv_d:
        c, h = hav_conv_d["ctrl"], hav_conv_d["hold"]
        ctrl_conv_rate = c.get("conversion_rate", 0) or 0
        hold_conv_rate = h.get("conversion_rate", 0) or 0
        ctrl_users_n = c.get("users", 0) or 0
        hold_users_n = h.get("users", 0) or 0
        hold_converters_n = h.get("converters", 0) or 0
        total_pop = ctrl_users_n + hold_users_n

        expected_hold_at_ctrl = hold_users_n * ctrl_conv_rate
        excess_converters = hold_converters_n - expected_hold_at_ctrl
        proj_holdout_total = total_pop * hold_conv_rate
        proj_ctrl_total = total_pop * ctrl_conv_rate
        potential_incremental = proj_holdout_total - proj_ctrl_total

        lines += [
            "### Havenly Pre-Converted (HAV PC)",
            "",
            "The holdout group converts at a significantly higher rate, suggesting the current email "
            "frequency is **suppressing conversions** for this segment.",
            "",
            f"- Control conversion rate: **{fmt_pct(ctrl_conv_rate)}**",
            f"- Holdout conversion rate: **{fmt_pct(hold_conv_rate)}**",
            f"- Excess holdout converters vs. expected at control rate: **{int(excess_converters):,}** users",
            f"- If the entire population converted at the holdout rate instead of the control rate, "
            f"we would expect **{int(potential_incremental):+,}** additional conversions across "
            f"{fmt_num(total_pop)} total users.",
            "",
        ]

    # ID: holdout outperforms → email suppressing
    if id_d:
        c, h = id_d["ctrl"], id_d["hold"]
        ctrl_rev_pu = c.get("revenue_per_user", 0) or 0
        hold_rev_pu = h.get("revenue_per_user", 0) or 0
        ctrl_users_n = c.get("users", 0) or 0
        hold_users_n = h.get("users", 0) or 0
        total_pop = ctrl_users_n + hold_users_n
        rev_diff = hold_rev_pu - ctrl_rev_pu  # holdout advantage
        potential_incremental = total_pop * (hold_rev_pu - ctrl_rev_pu)

        lines += [
            "### Interior Define (ID)",
            "",
            "The holdout group generates more revenue per user, suggesting the current email "
            "frequency may be suppressing purchases.",
            "",
            f"- Control revenue/user: **{fmt_money(ctrl_rev_pu)}**",
            f"- Holdout revenue/user: **{fmt_money(hold_rev_pu)}**",
            f"- Holdout advantage per user: **{fmt_money(rev_diff)}**",
            f"- If the entire population converted at the holdout revenue rate, potential additional "
            f"revenue across {fmt_num(total_pop)} users: **{fmt_money(potential_incremental)}**",
            "",
        ]

    # BW: control outperforms holdout → email drives purchases
    if bw_d:
        c, h = bw_d["ctrl"], bw_d["hold"]
        ctrl_rev_pu = c.get("revenue_per_user", 0) or 0
        hold_rev_pu = h.get("revenue_per_user", 0) or 0
        hold_users_n = h.get("users", 0) or 0
        hold_total_rev = h.get("total_revenue", 0) or 0
        rev_diff = ctrl_rev_pu - hold_rev_pu
        expected_hold_at_ctrl = hold_users_n * ctrl_rev_pu
        incremental_est = expected_hold_at_ctrl - hold_total_rev

        lines += [
            "### Burrow (BW)",
            "",
            "The control group generates more revenue per user than the holdout, suggesting email "
            "is incrementally driving purchases.",
            "",
            f"- Control revenue/user: **{fmt_money(ctrl_rev_pu)}**",
            f"- Holdout revenue/user: **{fmt_money(hold_rev_pu)}**",
            f"- Per-user differential: **{fmt_money(rev_diff)}** (control advantage)",
            f"- Holdout group size: {fmt_num(hold_users_n)} users",
            f"- Estimated incremental revenue from email (holdout at control rate − actual holdout): "
            f"**{fmt_money(incremental_est)}**",
            "",
            "> *Note: BW purchase rate difference is no longer statistically significant as of this "
            "report. The revenue differential has narrowed. Treat incremental estimate with caution.*"
            if not any(sig for _, m, _, _, sig, _ in sig_entries if _ == "BW" or (_ is None and m == "Purchase Rate")) else "",
            "",
        ]

    # ── Section 6: Changes from Previous Report ───────────────────────────────
    lines += [
        "---",
        "",
        "## 6. Changes from Previous Report (2/28 → {today})",
        "",
        "| Brand | Metric | 2/28 | {today} | Trend |",
        "|-------|--------|------|---------|-------|",
    ]

    b228 = BASELINE_228

    # HAV
    if hav_conv_d and hav_eng_d:
        c_conv, h_conv = hav_conv_d["ctrl"], hav_conv_d["hold"]
        c_eng, h_eng = hav_eng_d["ctrl"], hav_eng_d["hold"]

        cr_ctrl_now = c_conv.get("conversion_rate", 0) or 0
        cr_hold_now = h_conv.get("conversion_rate", 0) or 0
        d_conv_old = b228["HAV"]["delta_conv_pct"]  # +118.3
        d_conv_new = (cr_hold_now - cr_ctrl_now) / cr_ctrl_now * 100 if cr_ctrl_now else None

        ck_ctrl_now = c_eng.get("clicker_rate", 0) or 0
        ck_hold_now = h_eng.get("clicker_rate", 0) or 0
        d_click_old = b228["HAV"]["delta_click_pct"]  # +15.3
        d_click_new = (ck_hold_now - ck_ctrl_now) / ck_ctrl_now * 100 if ck_ctrl_now else None

        sp_ctrl_old = b228["HAV"]["sends_per_user_ctrl"]  # 31.71
        sp_hold_old = b228["HAV"]["sends_per_user_hold"]  # 26.30
        sp_ctrl_now = c_eng.get("sends_per_user", 0) or 0
        sp_hold_now = h_eng.get("sends_per_user", 0) or 0

        p_conv_old = b228["HAV"]["p_conv"]
        p_conv_new = next((p for brand, m, z, p, sig, d in sig_entries if brand == "HAV PC" and "Conv" in m), None)

        lines.append(
            f"| HAV PC | Conversion rate delta (hold vs ctrl) | {_pct_fmt(d_conv_old)} | "
            f"{_pct_fmt(d_conv_new)} | {_trend(d_conv_old, d_conv_new, higher_is_better=True)} |"
        )
        lines.append(
            f"| HAV PC | Clicker rate delta | {_pct_fmt(d_click_old)} | "
            f"{_pct_fmt(d_click_new)} | {_trend(d_click_old, d_click_new, higher_is_better=True)} |"
        )
        lines.append(
            f"| HAV PC | Ctrl sends/user | {sp_ctrl_old:.2f} | {sp_ctrl_now:.2f} | "
            f"{'More sends' if sp_ctrl_now > sp_ctrl_old else 'Fewer sends'} |"
        )
        lines.append(
            f"| HAV PC | Holdout sends/user | {sp_hold_old:.2f} | {sp_hold_now:.2f} | "
            f"{'More sends' if sp_hold_now > sp_hold_old else 'Fewer sends'} |"
        )
        if p_conv_new is not None:
            lines.append(
                f"| HAV PC | p-value (conversion rate) | {p_conv_old:.4f} | {p_conv_new:.5f} | "
                f"{'Still highly significant' if p_conv_new < 0.001 else 'Significant' if p_conv_new < 0.05 else 'No longer significant'} |"
            )

    # ID
    if id_d:
        c, h = id_d["ctrl"], id_d["hold"]
        pr_ctrl_now = c.get("purchase_rate", 0) or 0
        pr_hold_now = h.get("purchase_rate", 0) or 0
        sw_ctrl_now = c.get("swatch_conversion_rate", 0) or 0
        sw_hold_now = h.get("swatch_conversion_rate", 0) or 0
        rev_ctrl_now = c.get("revenue_per_user", 0) or 0
        rev_hold_now = h.get("revenue_per_user", 0) or 0

        d_pur_old = b228["ID"]["delta_purchase_pct"]   # +46.1
        d_pur_new = (pr_hold_now - pr_ctrl_now) / pr_ctrl_now * 100 if pr_ctrl_now else None
        d_sw_old  = b228["ID"]["delta_swatch_pct"]     # +221.0
        d_sw_new  = (sw_hold_now - sw_ctrl_now) / sw_ctrl_now * 100 if sw_ctrl_now else None
        d_rev_old = b228["ID"]["delta_rev_pct"]        # +23.8
        d_rev_new = (rev_hold_now - rev_ctrl_now) / rev_ctrl_now * 100 if rev_ctrl_now else None

        p_pur_old = b228["ID"]["p_purchase"]
        p_pur_new = next((p for brand, m, z, p, sig, d in sig_entries if brand == "ID" and "Purchase" in m), None)

        lines.append(
            f"| ID | Purchase rate delta (hold vs ctrl) | {_pct_fmt(d_pur_old)} | "
            f"{_pct_fmt(d_pur_new)} | {_trend(d_pur_old, d_pur_new, higher_is_better=True)} |"
        )
        lines.append(
            f"| ID | Swatch conv rate delta | {_pct_fmt(d_sw_old)} | "
            f"{_pct_fmt(d_sw_new)} | {_trend(d_sw_old, d_sw_new, higher_is_better=True)} |"
        )
        lines.append(
            f"| ID | Revenue/user delta | {_pct_fmt(d_rev_old)} | "
            f"{_pct_fmt(d_rev_new)} | {_trend(d_rev_old, d_rev_new, higher_is_better=True)} |"
        )
        if p_pur_new is not None:
            lines.append(
                f"| ID | p-value (purchase rate) | {p_pur_old:.5f} | {p_pur_new:.5f} | "
                f"{'Still highly significant' if p_pur_new < 0.001 else 'Significant' if p_pur_new < 0.05 else 'No longer significant'} |"
            )

    # BW
    if bw_d:
        c, h = bw_d["ctrl"], bw_d["hold"]
        pr_ctrl_now = c.get("purchase_rate", 0) or 0
        pr_hold_now = h.get("purchase_rate", 0) or 0
        rev_ctrl_now = c.get("revenue_per_user", 0) or 0
        rev_hold_now = h.get("revenue_per_user", 0) or 0

        d_pur_old = b228["BW"]["delta_purchase_pct"]   # -24.2
        d_pur_new = (pr_hold_now - pr_ctrl_now) / pr_ctrl_now * 100 if pr_ctrl_now else None
        d_rev_old = b228["BW"]["delta_rev_pct"]         # -25.1
        d_rev_new = (rev_hold_now - rev_ctrl_now) / rev_ctrl_now * 100 if rev_ctrl_now else None

        p_old = b228["BW"]["p_purchase"]
        p_new = next((p for brand, m, z, p, sig, d in sig_entries if brand == "BW" and "Purchase" in m), None)

        lines.append(
            f"| BW | Purchase rate delta (hold vs ctrl) | {_pct_fmt(d_pur_old)} | "
            f"{_pct_fmt(d_pur_new)} | {_trend(d_pur_old, d_pur_new, higher_is_better=False)} |"
        )
        lines.append(
            f"| BW | Revenue/user delta | {_pct_fmt(d_rev_old)} | "
            f"{_pct_fmt(d_rev_new)} | {_trend(d_rev_old, d_rev_new, higher_is_better=False)} |"
        )
        if p_new is not None:
            lines.append(
                f"| BW | p-value (purchase rate) | {p_old:.3f} | {p_new:.5f} | "
                f"{'Crossed above 0.05 ⚠' if p_old < 0.05 and p_new >= 0.05 else 'Still significant' if p_new < 0.05 else 'Not significant'} |"
            )

    lines.append("")

    # ── Section 7: Key Takeaways ──────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## 7. Key Takeaways",
        "",
    ]

    # HAV takeaway
    if hav_conv_d:
        c, h = hav_conv_d["ctrl"], hav_conv_d["hold"]
        cr_ctrl = c.get("conversion_rate", 0) or 0
        cr_hold = h.get("conversion_rate", 0) or 0
        d_conv_now = (cr_hold - cr_ctrl) / cr_ctrl * 100 if cr_ctrl else 0
        d_conv_old = b228["HAV"]["delta_conv_pct"]
        ratio = cr_hold / cr_ctrl if cr_ctrl else 0
        hav_p = next((p for brand, m, z, p, sig, d in sig_entries if brand == "HAV PC" and "Conv" in m), None)
        hav_sig = next((sig for brand, m, z, p, sig, d in sig_entries if brand == "HAV PC" and "Conv" in m), False)

        hav_note = (
            f"The holdout converts at {ratio:.1f}× the control rate "
            f"({fmt_pct(cr_hold)} vs {fmt_pct(cr_ctrl)})."
        )
        if hav_sig:
            p_str = f"p={hav_p:.4f}" if hav_p else "highly significant"
            hav_note += f" This is statistically significant ({p_str}). "
        hav_note += (
            f" The conversion gap has {'narrowed' if abs(d_conv_now) < abs(d_conv_old) else 'widened'} "
            f"from {_pct_fmt(d_conv_old)} to {_pct_fmt(d_conv_now)}, but remains extreme. "
            "Email frequency appears to be actively suppressing conversions for this segment. "
            "Reducing send frequency for HAV PC is strongly supported by the data."
        )

        # AI engagement note
        if hav_eng_d:
            c_e, h_e = hav_eng_d["ctrl"], hav_eng_d["hold"]
            ai_ctrl = c_e.get("explore_ai_rate", 0) or 0
            ai_hold = h_e.get("explore_ai_rate", 0) or 0
            if ai_hold != ai_ctrl and ai_ctrl > 0:
                ai_delta = (ai_hold - ai_ctrl) / ai_ctrl * 100
                hav_note += (
                    f" Holdout users also show a {_pct_fmt(ai_delta)} difference in `explore_with_ai` "
                    f"feature usage ({fmt_pct(ai_hold)} vs {fmt_pct(ai_ctrl)}), suggesting email "
                    "cadence may also affect AI feature engagement."
                )

        lines += [f"### Havenly Pre-Converted (HAV PC)", "", hav_note, ""]

    # ID takeaway
    if id_d:
        c, h = id_d["ctrl"], id_d["hold"]
        pr_ctrl = c.get("purchase_rate", 0) or 0
        pr_hold = h.get("purchase_rate", 0) or 0
        rev_ctrl = c.get("revenue_per_user", 0) or 0
        rev_hold = h.get("revenue_per_user", 0) or 0
        sw_ctrl = c.get("swatch_conversion_rate", 0) or 0
        sw_hold = h.get("swatch_conversion_rate", 0) or 0
        d_pur_now = (pr_hold - pr_ctrl) / pr_ctrl * 100 if pr_ctrl else 0
        d_pur_old = b228["ID"]["delta_purchase_pct"]
        d_sw_now = (sw_hold - sw_ctrl) / sw_ctrl * 100 if sw_ctrl else 0
        id_p = next((p for brand, m, z, p, sig, d in sig_entries if brand == "ID" and "Purchase" in m), None)
        id_sig = next((sig for brand, m, z, p, sig, d in sig_entries if brand == "ID" and "Purchase" in m), False)

        id_note = (
            f"The holdout generates {_pct_fmt(d_pur_now)} more in purchase rate and "
            f"a {_pct_fmt(d_sw_now)} higher swatch conversion rate vs. control "
            f"({fmt_pct(sw_hold)} vs {fmt_pct(sw_ctrl)})."
        )
        if id_sig:
            p_str = f"p={id_p:.5f}" if id_p else "highly significant"
            id_note += f" Both are highly statistically significant ({p_str}). "
        id_note += (
            f" The purchase rate gap is {'stable' if abs(d_pur_now - d_pur_old) < 5 else 'shifting'} "
            f"(2/28: {_pct_fmt(d_pur_old)} → today: {_pct_fmt(d_pur_now)}). "
            "Email frequency is suppressing purchases and especially swatch conversions at ID."
        )
        lines += [f"### Interior Define (ID)", "", id_note, ""]

    # BW takeaway — dynamic based on significance
    if bw_d:
        c, h = bw_d["ctrl"], bw_d["hold"]
        pr_ctrl = c.get("purchase_rate", 0) or 0
        pr_hold = h.get("purchase_rate", 0) or 0
        rev_ctrl = c.get("revenue_per_user", 0) or 0
        rev_hold = h.get("revenue_per_user", 0) or 0
        d_pur_now = (pr_hold - pr_ctrl) / pr_ctrl * 100 if pr_ctrl else 0
        d_pur_old = b228["BW"]["delta_purchase_pct"]
        rev_diff = rev_ctrl - rev_hold  # control advantage
        bw_purchase_p = next((p for brand, m, z, p, sig, d in sig_entries if brand == "BW" and "Purchase" in m), None)
        bw_purchase_sig = next((sig for brand, m, z, p, sig, d in sig_entries if brand == "BW" and "Purchase" in m), False)

        if bw_purchase_sig:
            bw_note = (
                f"The control group continues to outperform holdout on purchase rate "
                f"({fmt_pct(pr_ctrl)} vs {fmt_pct(pr_hold)}, {_pct_fmt(d_pur_now)}, "
                f"p={bw_purchase_p:.3f}). Email is incrementally driving purchases. "
                f"The revenue/user gap is {fmt_money(rev_diff)} in favor of control."
            )
        else:
            bw_note = (
                f"The purchase rate gap narrowed from {_pct_fmt(d_pur_old)} to {_pct_fmt(d_pur_now)} "
                f"and is **no longer statistically significant** "
                f"(p={bw_purchase_p:.3f} > 0.05, previously p=0.032). "
                f"The control group's revenue/user advantage ({fmt_money(rev_diff)}) persists but is shrinking. "
                f"Continue monitoring — the test may need a longer run to resolve."
            )
        lines += [f"### Burrow (BW)", "", bw_note, ""]

    lines += [
        "---",
        "",
        f"*Report generated: {today}. Test window: January 14, 2026 – {today}.*",
        "",
    ]

    # fix deferred f-string literals that use {today}
    report = "\n".join(lines)
    report = report.replace("## 6. Changes from Previous Report (2/28 → {today})", f"## 6. Changes from Previous Report (2/28 → {today})")
    report = report.replace("| Brand | Metric | 2/28 | {today} | Trend |", f"| Brand | Metric | 2/28 | {today} | Trend |")
    report = report.replace("| Brand | Metric | 2/28 | {today} | Trend |", f"| Brand | Metric | 2/28 | {today} | Trend |")
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Holdout frequency test results")
    parser.add_argument("--id-csv", metavar="PATH",
                        help="Path to ID Query Builder export CSV (optional)")
    parser.add_argument("--id-sends-ctrl", type=float, metavar="N",
                        help="ID control sends/user (from QB Query 2)")
    parser.add_argument("--id-sends-hold", type=float, metavar="N",
                        help="ID holdout sends/user (from QB Query 2)")
    args = parser.parse_args()

    today = date.today().isoformat()
    print(f"\nHoldout Frequency Test — Refreshed Results")
    print(f"Test window: 2026-01-14 through {today}")
    print(f"Running queries against Braze datashare in Snowflake...")

    client = get_snowflake_client(schema=SCHEMA, database=DB)
    sig_entries = []
    all_csv_rows: dict[str, list[dict]] = {}
    results: dict = {}  # populated for markdown report

    # ------------------------------------------------------------------
    # BURROW
    # ------------------------------------------------------------------
    cfg_bw = BRAND_CONFIG["BW"]
    print(f"\n[BW] Running Burrow purchase + swatch query...")
    bw_rows = query_bw(client, cfg_bw)
    bw = row_to_dict(bw_rows)

    if "control" in bw and "holdout" in bw:
        ctrl, hold = bw["control"], bw["holdout"]
        print_section("Burrow — Purchase & Revenue")
        print_table(
            ["Metric", "Control", "Holdout", "Delta"],
            [
                ["Users",             fmt_num(ctrl["users"]),             fmt_num(hold["users"]),             "—"],
                ["Purchasers",        fmt_num(ctrl["purchasers"]),        fmt_num(hold["purchasers"]),        "—"],
                ["Purchase Rate",     fmt_pct(ctrl["purchase_rate"]),     fmt_pct(hold["purchase_rate"]),
                 delta_pct(hold["purchase_rate"], ctrl["purchase_rate"])],
                ["Total Revenue",     fmt_money(ctrl["total_revenue"]),   fmt_money(hold["total_revenue"]),   "—"],
                ["Revenue/User",      fmt_money(ctrl["revenue_per_user"]), fmt_money(hold["revenue_per_user"]),
                 delta_pct(hold["revenue_per_user"], ctrl["revenue_per_user"])],
                ["Avg Order Value",   fmt_money(ctrl["average_order_value"] or 0), fmt_money(hold["average_order_value"] or 0),
                 delta_pct(hold["average_order_value"] or 0, ctrl["average_order_value"] or 0)],
                ["Swatch Converters", fmt_num(ctrl["swatch_converters"]), fmt_num(hold["swatch_converters"]), "—"],
                ["Swatch Conv Rate",  fmt_pct(ctrl["swatch_conversion_rate"]),
                 fmt_pct(hold["swatch_conversion_rate"]),
                 delta_pct(hold["swatch_conversion_rate"], ctrl["swatch_conversion_rate"])],
            ]
        )
        # Significance
        z, p, sig = sig_test(ctrl["users"], ctrl["purchasers"], hold["users"], hold["purchasers"])
        sig_entries.append(("BW", "Purchase Rate", z, p, sig,
                            "Control higher" if ctrl["purchase_rate"] > hold["purchase_rate"] else "Holdout higher"))
        z2, p2, sig2 = sig_test(ctrl["users"], ctrl["swatch_converters"], hold["users"], hold["swatch_converters"])
        sig_entries.append(("BW", "Swatch Conv Rate", z2, p2, sig2,
                            "Control higher" if ctrl["swatch_conversion_rate"] > hold["swatch_conversion_rate"] else "Holdout higher"))

        all_csv_rows["BW_revenue"] = [{**r, "section": "BW_revenue"} for r in bw_rows]
        results["bw"] = {"ctrl": ctrl, "hold": hold}
    else:
        print(f"  WARNING: unexpected result groups: {list(bw.keys())}")

    # BW sends/user (email + SMS)
    print(f"\n[BW] Running Burrow sends/user query...")
    bw_send_rows = query_bw_sends(client, cfg_bw)
    bw_sends_by_group = row_to_dict(bw_send_rows)
    if "control" in bw_sends_by_group and "holdout" in bw_sends_by_group:
        c, h = bw_sends_by_group["control"], bw_sends_by_group["holdout"]
        print_section("Burrow — Send Frequency (email + SMS)")
        print_table(
            ["Metric", "Control", "Holdout", "Delta"],
            [
                ["Users",              fmt_num(c["users"]),                  fmt_num(h["users"]),                  "—"],
                ["Sends/User",         f"{c['sends_per_user']:.2f}",         f"{h['sends_per_user']:.2f}",
                 delta_pct(h["sends_per_user"], c["sends_per_user"])],
                ["Email Sends/User",   f"{c['email_sends_per_user']:.2f}",   f"{h['email_sends_per_user']:.2f}",
                 delta_pct(h["email_sends_per_user"], c["email_sends_per_user"])],
                ["SMS Sends/User",     f"{c['sms_sends_per_user']:.2f}",     f"{h['sms_sends_per_user']:.2f}",     "—"],
            ]
        )
        results["bw_sends"] = {"ctrl": c, "hold": h}

    # ------------------------------------------------------------------
    # HAVENLY PC — Conversion
    # ------------------------------------------------------------------
    cfg_hav = BRAND_CONFIG["HAV"]
    print(f"\n[HAV] Running Havenly PC conversion query...")
    hav_conv_rows = query_hav_conversion(client, cfg_hav)
    hav_conv = row_to_dict(hav_conv_rows)

    if "control" in hav_conv and "holdout" in hav_conv:
        ctrl, hold = hav_conv["control"], hav_conv["holdout"]
        print_section("Havenly Pre-Converted — Conversion")
        print_table(
            ["Metric", "Control", "Holdout", "Delta"],
            [
                ["Users",            fmt_num(ctrl["users"]),            fmt_num(hold["users"]),            "—"],
                ["Converters",       fmt_num(ctrl["converters"]),       fmt_num(hold["converters"]),       "—"],
                ["Conversion Rate",  fmt_pct(ctrl["conversion_rate"]),  fmt_pct(hold["conversion_rate"]),
                 delta_pct(hold["conversion_rate"], ctrl["conversion_rate"])],
                ["Design Fee Events",fmt_num(ctrl["total_design_fee_proxy_events"]),
                 fmt_num(hold["total_design_fee_proxy_events"]), "—"],
            ]
        )
        z, p, sig = sig_test(ctrl["users"], ctrl["converters"], hold["users"], hold["converters"])
        sig_entries.append(("HAV PC", "Design Fee Conv Rate", z, p, sig,
                            "Holdout higher" if hold["conversion_rate"] > ctrl["conversion_rate"] else "Control higher"))
        all_csv_rows["HAV_conversion"] = [{**r, "section": "HAV_conversion"} for r in hav_conv_rows]
        results["hav_conv"] = {"ctrl": ctrl, "hold": hold}

    # ------------------------------------------------------------------
    # HAVENLY PC — Engagement
    # ------------------------------------------------------------------
    print(f"\n[HAV] Running Havenly PC engagement query...")
    hav_eng_rows = query_hav_engagement(client, cfg_hav)
    hav_eng = row_to_dict(hav_eng_rows)

    if "control" in hav_eng and "holdout" in hav_eng:
        ctrl, hold = hav_eng["control"], hav_eng["holdout"]
        print_section("Havenly Pre-Converted — Email Engagement")
        print_table(
            ["Metric", "Control", "Holdout", "Delta"],
            [
                ["Users",              fmt_num(ctrl["users"]),    fmt_num(hold["users"]),    "—"],
                ["Sends/User",         f"{ctrl['sends_per_user']:.2f}", f"{hold['sends_per_user']:.2f}",
                 delta_pct(hold["sends_per_user"], ctrl["sends_per_user"])],
                ["Total Clicks",       fmt_num(ctrl["total_clicks"]),  fmt_num(hold["total_clicks"]),  "—"],
                ["Clicks/User",        f"{ctrl['clicks_per_user']:.4f}", f"{hold['clicks_per_user']:.4f}",
                 delta_pct(hold["clicks_per_user"], ctrl["clicks_per_user"])],
                ["Unique Clicks/User", f"{ctrl['unique_clicks_per_user']:.4f}", f"{hold['unique_clicks_per_user']:.4f}",
                 delta_pct(hold["unique_clicks_per_user"], ctrl["unique_clicks_per_user"])],
                ["Unique Clickers",    fmt_num(ctrl["unique_clickers"]), fmt_num(hold["unique_clickers"]), "—"],
                ["Clicker Rate",       fmt_pct(ctrl["clicker_rate"]),  fmt_pct(hold["clicker_rate"]),
                 delta_pct(hold["clicker_rate"], ctrl["clicker_rate"])],
                ["Opens/User",         f"{ctrl['opens_per_user']:.4f}", f"{hold['opens_per_user']:.4f}",
                 delta_pct(hold["opens_per_user"], ctrl["opens_per_user"])],
            ]
        )
        print_section("Havenly Pre-Converted — AI Feature Engagement")
        print_table(
            ["Metric", "Control", "Holdout", "Delta"],
            [
                ["Explore AI Users",   fmt_num(ctrl["explore_ai_users"]),   fmt_num(hold["explore_ai_users"]),   "—"],
                ["Explore AI Rate",    fmt_pct(ctrl["explore_ai_rate"]),    fmt_pct(hold["explore_ai_rate"]),
                 delta_pct(hold["explore_ai_rate"], ctrl["explore_ai_rate"])],
                ["Explore AI Ev/User", f"{ctrl['explore_ai_per_user']:.4f}", f"{hold['explore_ai_per_user']:.4f}", "—"],
                ["AI Session Users",   fmt_num(ctrl["ai_session_users"]),   fmt_num(hold["ai_session_users"]),   "—"],
                ["AI Session Rate",    fmt_pct(ctrl["ai_session_rate"]),    fmt_pct(hold["ai_session_rate"]),
                 delta_pct(hold["ai_session_rate"], ctrl["ai_session_rate"])],
                ["AI Session Ev/User", f"{ctrl['ai_session_per_user']:.4f}", f"{hold['ai_session_per_user']:.4f}", "—"],
            ]
        )
        # Clicker rate significance
        z, p, sig = sig_test(ctrl["users"], ctrl["unique_clickers"], hold["users"], hold["unique_clickers"])
        sig_entries.append(("HAV PC", "Clicker Rate", z, p, sig,
                            "Holdout higher" if hold["clicker_rate"] > ctrl["clicker_rate"] else "Control higher"))
        all_csv_rows["HAV_engagement"] = [{**r, "section": "HAV_engagement"} for r in hav_eng_rows]
        results["hav_eng"] = {"ctrl": ctrl, "hold": hold}

    # ------------------------------------------------------------------
    # INTERIOR DEFINE — from QB CSV (if provided)
    # ------------------------------------------------------------------
    if args.id_csv:
        id_rows = load_id_csv(args.id_csv)
        id_data = row_to_dict(id_rows)
        if "control" in id_data and "holdout" in id_data:
            ctrl, hold = id_data["control"], id_data["holdout"]
            print_section("Interior Define — Purchase & Revenue (from QB export)")
            print_table(
                ["Metric", "Control", "Holdout", "Delta"],
                [
                    ["Users",             fmt_num(ctrl["users"]),             fmt_num(hold["users"]),             "—"],
                    ["Purchasers",        fmt_num(ctrl["purchasers"]),        fmt_num(hold["purchasers"]),        "—"],
                    ["Purchase Rate",     fmt_pct(ctrl["purchase_rate"]),     fmt_pct(hold["purchase_rate"]),
                     delta_pct(hold["purchase_rate"], ctrl["purchase_rate"])],
                    ["Total Revenue",     fmt_money(ctrl["total_revenue"]),   fmt_money(hold["total_revenue"]),   "—"],
                    ["Revenue/User",      fmt_money(ctrl["revenue_per_user"]), fmt_money(hold["revenue_per_user"]),
                     delta_pct(hold["revenue_per_user"], ctrl["revenue_per_user"])],
                    ["Avg Order Value",   fmt_money(ctrl["average_order_value"] or 0), fmt_money(hold["average_order_value"] or 0),
                     delta_pct(hold["average_order_value"] or 0, ctrl["average_order_value"] or 0)],
                    ["Swatch Converters", fmt_num(ctrl["swatch_converters"]), fmt_num(hold["swatch_converters"]), "—"],
                    ["Swatch Conv Rate",  fmt_pct(ctrl["swatch_conversion_rate"]),
                     fmt_pct(hold["swatch_conversion_rate"]),
                     delta_pct(hold["swatch_conversion_rate"], ctrl["swatch_conversion_rate"])],
                ]
            )
            z, p, sig = sig_test(ctrl["users"], ctrl["purchasers"], hold["users"], hold["purchasers"])
            sig_entries.append(("ID", "Purchase Rate", z, p, sig,
                                "Holdout higher" if hold["purchase_rate"] > ctrl["purchase_rate"] else "Control higher"))
            z2, p2, sig2 = sig_test(ctrl["users"], ctrl["swatch_converters"], hold["users"], hold["swatch_converters"])
            sig_entries.append(("ID", "Swatch Conv Rate", z2, p2, sig2,
                                "Holdout higher" if hold["swatch_conversion_rate"] > ctrl["swatch_conversion_rate"] else "Control higher"))
            all_csv_rows["ID_revenue"] = [{**r, "section": "ID_revenue"} for r in id_rows]
            results["id"] = {"ctrl": ctrl, "hold": hold}
        else:
            print(f"\n  WARNING: ID CSV groups unexpected: {list(id_data.keys())}")

    if args.id_sends_ctrl is not None and args.id_sends_hold is not None:
        results["id_sends"] = {"ctrl": args.id_sends_ctrl, "hold": args.id_sends_hold}

    # ------------------------------------------------------------------
    # Statistical significance summary
    # ------------------------------------------------------------------
    print_section("Statistical Significance")
    print_sig_table(sig_entries)

    # ------------------------------------------------------------------
    # ID: print updated QB SQL
    # ------------------------------------------------------------------
    print_id_qb_sql()

    # ------------------------------------------------------------------
    # Save CSV
    # ------------------------------------------------------------------
    exports_dir = Path(__file__).parent.parent.parent / "exports"
    exports_dir.mkdir(exist_ok=True)
    output_path = exports_dir / f"holdout_frequency_results_{today}.csv"
    if all_csv_rows:
        all_rows_flat = []
        for rows in all_csv_rows.values():
            all_rows_flat.extend(rows)
        # Flatten to simple dicts without nested section key
        if all_rows_flat:
            # Collect all unique keys across all rows (sections have different columns)
            all_keys: list[str] = []
            seen_keys: set[str] = set()
            for row in all_rows_flat:
                for k in row.keys():
                    if k not in seen_keys:
                        all_keys.append(k)
                        seen_keys.add(k)
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore",
                                        restval="")
                writer.writeheader()
                writer.writerows(all_rows_flat)
            print(f"\nSaved: {output_path}")

    # ------------------------------------------------------------------
    # Generate markdown report
    # ------------------------------------------------------------------
    results["sig_entries"] = sig_entries
    report_md = generate_markdown_report(results, today)
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"holdout_frequency_{today}.md"
    report_path.write_text(report_md)
    print(f"\nSaved report: {report_path}")

    client.close()
    print(f"\nDone. Test window: 2026-01-14 through {today}\n")


if __name__ == "__main__":
    main()

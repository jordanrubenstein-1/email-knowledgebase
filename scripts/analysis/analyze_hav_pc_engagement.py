#!/usr/bin/env python3
"""
HAV Pre-Converted Email Engagement Analysis

Two key questions:
1. Merch sales: Do pre-converted users buy merch, and how does email engagement
   correlate with merch purchases?
2. Design conversion: Do dormant email users convert to design packages at
   different rates than actively-engaged email users?

Cohort methodology for Q2:
  - Reference date: 6 months ago (2025-10-22)
  - Cohort: HAV users with no design_fee event as of that date AND received
    at least one email in the 90-day window before it (2025-07-24 to 2025-10-22)
  - Engagement classification: email opens/clicks in that 90-day window
  - Outcome window: design_fee events from 2025-10-22 to 2026-04-22

Usage:
    uv run python scripts/analysis/analyze_hav_pc_engagement.py
    uv run python scripts/analysis/analyze_hav_pc_engagement.py \\
        --csv ~/Downloads/"Daily_Send_List_-_Pre_Converted_export 2.csv" \\
        --output reports/hav-pc-engagement-analysis.md
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
HAV = "664223fb71bcf3005760dfc2"

TODAY = datetime(2026, 4, 22)
COHORT_REF_DATE = TODAY - timedelta(days=180)   # 2025-10-22
ENGAGEMENT_WINDOW_DAYS = 90
ENGAGEMENT_START = COHORT_REF_DATE - timedelta(days=ENGAGEMENT_WINDOW_DAYS)  # 2025-07-24

DEFAULT_CSV = Path(__file__).parent.parent.parent.parent.parent / "Downloads" / "Daily_Send_List_-_Pre_Converted_export 2.csv"
DEFAULT_OUTPUT = Path(__file__).parent.parent.parent / "reports" / "hav-pc-engagement-analysis.md"

# ── Reusable milestone CTE ────────────────────────────────────────────────────
MILESTONES_CTE = f"""
MILESTONES AS (
    SELECT
        USER_ID,
        MIN(CASE WHEN NAME IN ('design_fee', 'design_fee_fe') THEN TO_TIMESTAMP(TIME) END) AS first_design_fee,
        MIN(CASE WHEN NAME = 'merch_order_completed_fe' THEN TO_TIMESTAMP(TIME) END) AS first_merch_order,
        MIN(CASE WHEN NAME IN ('account_created', 'account_created_fe') THEN TO_TIMESTAMP(TIME) END) AS first_account_created
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
      AND NAME IN ('design_fee', 'design_fee_fe', 'merch_order_completed_fe',
                   'account_created', 'account_created_fe')
    GROUP BY USER_ID
)"""


def load_appboy_ids(csv_path: Path) -> tuple[list[str], int]:
    """Read Appboy IDs and total count from the pre-converted export CSV."""
    ids, total = [], 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            aid = (row.get("Appboy ID") or "").strip()
            if aid:
                ids.append(aid)
    return ids, total


# ── Snowflake-side pre-converted cohort definition ────────────────────────────
# MCP_READER role is read-only — we cannot create tables.
# Instead, define "current pre-converted send list" as:
#   HAV users emailed in the last 90 days, no design_fee ever, not unsubscribed.
# This is a very close proxy for the actual send segment.

PRECONV_CTE = f"""
UNSUBS AS (
    SELECT DISTINCT USER_ID
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
),
CONVERTERS AS (
    SELECT DISTINCT USER_ID
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
      AND NAME IN ('design_fee', 'design_fee_fe')
),
RECENT_SENDS AS (
    SELECT DISTINCT USER_ID
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -90, CURRENT_TIMESTAMP())
),
SEND_LIST AS (
    SELECT r.USER_ID
    FROM RECENT_SENDS r
    WHERE NOT EXISTS (SELECT 1 FROM CONVERTERS c WHERE c.USER_ID = r.USER_ID)
      AND NOT EXISTS (SELECT 1 FROM UNSUBS u WHERE u.USER_ID = r.USER_ID)
)"""


# ── Section 1: Current send-list snapshot ────────────────────────────────────

def query_send_list_profile(client) -> list[dict]:
    """Breakdown of the current send list by lifecycle sub-stage."""
    sql = f"""
WITH
{PRECONV_CTE},
{MILESTONES_CTE}
SELECT
    CASE
        WHEN m.first_design_fee IS NOT NULL THEN 'Converted (on list in error?)'
        WHEN m.first_merch_order IS NOT NULL THEN 'Pre-conv — has merch purchase'
        WHEN m.first_account_created IS NOT NULL THEN 'Pre-conv — account, no merch'
        ELSE 'Email-only (no account)'
    END AS sub_stage,
    COUNT(*) AS users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM SEND_LIST s
LEFT JOIN MILESTONES m ON s.USER_ID = m.USER_ID
GROUP BY 1
ORDER BY 2 DESC
"""
    return client.execute_query(sql)


def query_merch_purchase_profile(client) -> list[dict]:
    """Email engagement in the 90 days BEFORE a merch purchase, for pre-converted buyers."""
    sql = f"""
WITH
{PRECONV_CTE},
{MILESTONES_CTE},
-- Pre-conv merch buyers on this send list
MERCH_BUYERS AS (
    SELECT s.USER_ID, m.first_merch_order
    FROM SEND_LIST s
    JOIN MILESTONES m ON s.USER_ID = m.USER_ID
    WHERE m.first_merch_order IS NOT NULL
      AND m.first_design_fee IS NULL
),
-- Email engagement in 90-day window before their first merch purchase
PRE_PURCHASE_ENGAGEMENT AS (
    SELECT
        b.USER_ID,
        b.first_merch_order,
        COUNT(DISTINCT CASE WHEN ev.NAME = 'send' THEN ev.EVENT_ID END) AS sends_before,
        COUNT(DISTINCT CASE WHEN ev.NAME = 'open' THEN ev.EVENT_ID END) AS opens_before,
        COUNT(DISTINCT CASE WHEN ev.NAME = 'click' THEN ev.EVENT_ID END) AS clicks_before
    FROM MERCH_BUYERS b
    LEFT JOIN (
        SELECT USER_ID, 'send' AS NAME, ID AS EVENT_ID, TO_TIMESTAMP(TIME) AS event_ts
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
        UNION ALL
        SELECT USER_ID, 'open', ID, TO_TIMESTAMP(TIME)
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
        WHERE APP_GROUP_ID = '{HAV}' AND (MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false')
        UNION ALL
        SELECT USER_ID, 'click', ID, TO_TIMESTAMP(TIME)
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
    ) ev ON b.USER_ID = ev.USER_ID
         AND ev.event_ts BETWEEN b.first_merch_order - INTERVAL '90 days' AND b.first_merch_order
    GROUP BY b.USER_ID, b.first_merch_order
)
SELECT
    CASE
        WHEN clicks_before > 0 THEN '3 — Clicked email before purchase'
        WHEN opens_before > 0 THEN '2 — Opened email (no click)'
        WHEN sends_before > 0 THEN '1 — Received email (no open)'
        ELSE '0 — No email touch in prior 90d'
    END AS email_engagement_tier,
    COUNT(*) AS buyers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_buyers,
    ROUND(AVG(sends_before), 1) AS avg_sends,
    ROUND(AVG(opens_before), 1) AS avg_opens,
    ROUND(AVG(clicks_before), 1) AS avg_clicks
FROM PRE_PURCHASE_ENGAGEMENT
GROUP BY 1
ORDER BY 1 DESC
"""
    return client.execute_query(sql)


def query_merch_email_attribution(client) -> list[dict]:
    """Overall email engagement summary for the current send list, merch buyers vs non-buyers."""
    # Trailing 90 days from today
    cutoff = (TODAY - timedelta(days=90)).strftime("%Y-%m-%d")
    sql = f"""
WITH
{PRECONV_CTE},
{MILESTONES_CTE},
RECENT_ENGAGEMENT AS (
    SELECT USER_ID,
           MAX(CASE WHEN NAME = 'open' THEN event_ts END) AS last_open,
           MAX(CASE WHEN NAME = 'click' THEN event_ts END) AS last_click,
           COUNT(DISTINCT CASE WHEN NAME = 'send' THEN EVENT_ID END) AS sends_90d,
           COUNT(DISTINCT CASE WHEN NAME = 'open' THEN EVENT_ID END) AS opens_90d,
           COUNT(DISTINCT CASE WHEN NAME = 'click' THEN EVENT_ID END) AS clicks_90d
    FROM (
        SELECT USER_ID, 'send' AS NAME, ID AS EVENT_ID, TO_TIMESTAMP(TIME) AS event_ts
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV}' AND TO_TIMESTAMP(TIME) >= '{cutoff}'
        UNION ALL
        SELECT USER_ID, 'open', ID, TO_TIMESTAMP(TIME)
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
        WHERE APP_GROUP_ID = '{HAV}' AND TO_TIMESTAMP(TIME) >= '{cutoff}'
          AND (MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false')
        UNION ALL
        SELECT USER_ID, 'click', ID, TO_TIMESTAMP(TIME)
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
        WHERE APP_GROUP_ID = '{HAV}' AND TO_TIMESTAMP(TIME) >= '{cutoff}'
    )
    GROUP BY USER_ID
),
CLASSIFIED AS (
    SELECT
        s.USER_ID,
        m.first_design_fee IS NOT NULL AS is_converted,
        m.first_merch_order IS NOT NULL AS has_merch,
        CASE
            WHEN e.clicks_90d > 0 THEN 'Active — Clicked'
            WHEN e.opens_90d > 0 THEN 'Active — Opened only'
            WHEN e.sends_90d > 0 THEN 'Dormant — Received, no open'
            ELSE 'Dormant — No recent sends'
        END AS engagement_tier,
        COALESCE(e.sends_90d, 0) AS sends_90d,
        COALESCE(e.opens_90d, 0) AS opens_90d,
        COALESCE(e.clicks_90d, 0) AS clicks_90d
    FROM SEND_LIST s
    LEFT JOIN MILESTONES m ON s.USER_ID = m.USER_ID
    LEFT JOIN RECENT_ENGAGEMENT e ON s.USER_ID = e.USER_ID
)
SELECT
    engagement_tier,
    COUNT(*) AS users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_list,
    SUM(CASE WHEN has_merch THEN 1 ELSE 0 END) AS merch_buyers,
    ROUND(100.0 * SUM(CASE WHEN has_merch THEN 1 ELSE 0 END) / COUNT(*), 2) AS merch_rate_pct,
    ROUND(AVG(sends_90d), 1) AS avg_sends_90d,
    ROUND(AVG(CASE WHEN sends_90d > 0 THEN opens_90d::FLOAT / sends_90d END) * 100, 1) AS avg_open_rate_pct
FROM CLASSIFIED
GROUP BY engagement_tier
ORDER BY engagement_tier
"""
    return client.execute_query(sql)


# ── Section 2: Design conversion cohort ──────────────────────────────────────

def query_design_conversion_cohort(client) -> list[dict]:
    """
    Cohort analysis: HAV pre-conv users who received emails in the 90-day window
    before 2025-10-22. Classify engagement → track design_fee within 6 months.
    """
    eng_start = ENGAGEMENT_START.strftime("%Y-%m-%d")   # 2025-07-24
    ref_date  = COHORT_REF_DATE.strftime("%Y-%m-%d")    # 2025-10-22
    end_date  = TODAY.strftime("%Y-%m-%d")              # 2026-04-22

    sql = f"""
WITH
{MILESTONES_CTE},
-- Step 1: Users who were emailed in the 90-day engagement window AND had no design_fee by ref_date
COHORT AS (
    SELECT DISTINCT s.USER_ID
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
    LEFT JOIN MILESTONES m ON s.USER_ID = m.USER_ID
    WHERE s.APP_GROUP_ID = '{HAV}'
      AND TO_TIMESTAMP(s.TIME) BETWEEN '{eng_start}' AND '{ref_date}'
      AND (m.first_design_fee IS NULL OR m.first_design_fee > '{ref_date}')
),
-- Step 2: Classify engagement in the 90-day window
ENGAGEMENT AS (
    SELECT USER_ID,
           COUNT(DISTINCT CASE WHEN NAME = 'open' THEN EVENT_ID END) AS opens,
           COUNT(DISTINCT CASE WHEN NAME = 'click' THEN EVENT_ID END) AS clicks,
           COUNT(DISTINCT CASE WHEN NAME = 'send' THEN EVENT_ID END) AS sends
    FROM (
        SELECT USER_ID, 'send' AS NAME, ID AS EVENT_ID
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
          AND TO_TIMESTAMP(TIME) BETWEEN '{eng_start}' AND '{ref_date}'
        UNION ALL
        SELECT USER_ID, 'open', ID
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
          AND TO_TIMESTAMP(TIME) BETWEEN '{eng_start}' AND '{ref_date}'
          AND (MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false')
        UNION ALL
        SELECT USER_ID, 'click', ID
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
          AND TO_TIMESTAMP(TIME) BETWEEN '{eng_start}' AND '{ref_date}'
    )
    GROUP BY USER_ID
),
-- Step 3: Tag each cohort member with their engagement tier
CLASSIFIED AS (
    SELECT
        c.USER_ID,
        CASE
            WHEN e.clicks > 0 THEN 'Active — Clicked'
            WHEN e.opens > 0 THEN 'Active — Opened only'
            ELSE 'Dormant — No opens'
        END AS engagement_tier,
        COALESCE(e.sends, 0) AS sends,
        COALESCE(e.opens, 0) AS opens,
        COALESCE(e.clicks, 0) AS clicks
    FROM COHORT c
    LEFT JOIN ENGAGEMENT e ON c.USER_ID = e.USER_ID
),
-- Step 4: Track design_fee conversion in the 6-month forward window
OUTCOMES AS (
    SELECT
        cl.USER_ID,
        cl.engagement_tier,
        cl.sends,
        cl.opens,
        cl.clicks,
        (m.first_design_fee IS NOT NULL
         AND m.first_design_fee > '{ref_date}'
         AND m.first_design_fee <= '{end_date}') AS converted_to_design,
        (m.first_merch_order IS NOT NULL
         AND m.first_merch_order > '{ref_date}'
         AND m.first_merch_order <= '{end_date}') AS bought_merch_post_ref
    FROM CLASSIFIED cl
    LEFT JOIN MILESTONES m ON cl.USER_ID = m.USER_ID
)
SELECT
    engagement_tier,
    COUNT(*) AS cohort_users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_cohort,
    SUM(CASE WHEN converted_to_design THEN 1 ELSE 0 END) AS converted,
    ROUND(100.0 * SUM(CASE WHEN converted_to_design THEN 1 ELSE 0 END) / COUNT(*), 2) AS conversion_rate_pct,
    SUM(CASE WHEN bought_merch_post_ref THEN 1 ELSE 0 END) AS merch_buyers_post,
    ROUND(100.0 * SUM(CASE WHEN bought_merch_post_ref THEN 1 ELSE 0 END) / COUNT(*), 2) AS merch_rate_post_pct,
    ROUND(AVG(sends), 1) AS avg_sends,
    ROUND(AVG(opens), 1) AS avg_opens,
    ROUND(AVG(clicks), 1) AS avg_clicks
FROM OUTCOMES
GROUP BY engagement_tier
ORDER BY engagement_tier DESC
"""
    return client.execute_query(sql)


def query_design_conversion_by_send_count(client) -> list[dict]:
    """Within the dormant tier, does send count (exposure) predict later conversion?"""
    eng_start = ENGAGEMENT_START.strftime("%Y-%m-%d")
    ref_date  = COHORT_REF_DATE.strftime("%Y-%m-%d")
    end_date  = TODAY.strftime("%Y-%m-%d")

    sql = f"""
WITH
{MILESTONES_CTE},
COHORT AS (
    SELECT DISTINCT s.USER_ID
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
    LEFT JOIN MILESTONES m ON s.USER_ID = m.USER_ID
    WHERE s.APP_GROUP_ID = '{HAV}'
      AND TO_TIMESTAMP(s.TIME) BETWEEN '{eng_start}' AND '{ref_date}'
      AND (m.first_design_fee IS NULL OR m.first_design_fee > '{ref_date}')
),
ENGAGEMENT AS (
    SELECT USER_ID,
           COUNT(DISTINCT CASE WHEN NAME = 'open' THEN EVENT_ID END) AS opens,
           COUNT(DISTINCT CASE WHEN NAME = 'send' THEN EVENT_ID END) AS sends
    FROM (
        SELECT USER_ID, 'send' AS NAME, ID AS EVENT_ID
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
          AND TO_TIMESTAMP(TIME) BETWEEN '{eng_start}' AND '{ref_date}'
        UNION ALL
        SELECT USER_ID, 'open', ID
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
        WHERE APP_GROUP_ID = '{HAV}'
          AND TO_TIMESTAMP(TIME) BETWEEN '{eng_start}' AND '{ref_date}'
          AND (MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false')
    )
    GROUP BY USER_ID
),
DORMANT_ONLY AS (
    SELECT c.USER_ID,
           COALESCE(e.sends, 0) AS sends,
           CASE
               WHEN COALESCE(e.sends, 0) <= 4 THEN '01-04 sends'
               WHEN COALESCE(e.sends, 0) <= 8 THEN '05-08 sends'
               WHEN COALESCE(e.sends, 0) <= 12 THEN '09-12 sends'
               ELSE '13+ sends'
           END AS send_bucket
    FROM COHORT c
    LEFT JOIN ENGAGEMENT e ON c.USER_ID = e.USER_ID
    WHERE COALESCE(e.opens, 0) = 0
)
SELECT
    d.send_bucket,
    COUNT(*) AS users,
    SUM(CASE WHEN m.first_design_fee IS NOT NULL
              AND m.first_design_fee > '{ref_date}'
              AND m.first_design_fee <= '{end_date}' THEN 1 ELSE 0 END) AS converted,
    ROUND(100.0 * SUM(CASE WHEN m.first_design_fee IS NOT NULL
                             AND m.first_design_fee > '{ref_date}'
                             AND m.first_design_fee <= '{end_date}' THEN 1 ELSE 0 END)
          / COUNT(*), 2) AS conversion_rate_pct
FROM DORMANT_ONLY d
LEFT JOIN MILESTONES m ON d.USER_ID = m.USER_ID
GROUP BY d.send_bucket
ORDER BY d.send_bucket
"""
    return client.execute_query(sql)


def query_merch_by_campaign_type(client) -> list[dict]:
    """For merch buyers on the send list, what campaign types drove the last click?"""
    sql = f"""
WITH
{PRECONV_CTE},
{MILESTONES_CTE},
MERCH_BUYERS AS (
    SELECT s.USER_ID, m.first_merch_order
    FROM SEND_LIST s
    JOIN MILESTONES m ON s.USER_ID = m.USER_ID
    WHERE m.first_merch_order IS NOT NULL AND m.first_design_fee IS NULL
),
LAST_CLICK AS (
    SELECT
        b.USER_ID,
        cl.CAMPAIGN_API_ID,
        TO_TIMESTAMP(cl.TIME) AS click_ts,
        ROW_NUMBER() OVER (PARTITION BY b.USER_ID ORDER BY TO_TIMESTAMP(cl.TIME) DESC) AS rn
    FROM MERCH_BUYERS b
    JOIN {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED cl
        ON b.USER_ID = cl.USER_ID
       AND cl.APP_GROUP_ID = '{HAV}'
       AND TO_TIMESTAMP(cl.TIME) BETWEEN b.first_merch_order - INTERVAL '30 days' AND b.first_merch_order
    WHERE cl.IS_SUSPECTED_BOT_CLICK IS NULL OR cl.IS_SUSPECTED_BOT_CLICK = 'false'
),
ATTRIBUTED AS (
    SELECT lc.USER_ID, c.NAME AS campaign_name
    FROM LAST_CLICK lc
    LEFT JOIN {DB}.{SCHEMA}.CHANGELOGS_CAMPAIGN_SHARED c ON lc.CAMPAIGN_API_ID = c.API_ID
    WHERE lc.rn = 1
)
SELECT
    CASE
        WHEN campaign_name LIKE '%_CONV_%' THEN 'Converted audience campaign'
        WHEN campaign_name LIKE '%_PC_%'   THEN 'Pre-converted audience campaign'
        WHEN campaign_name LIKE '%merch%' OR campaign_name ILIKE '%shop%' THEN 'Shop/merch campaign'
        WHEN campaign_name LIKE 'P_EM_%'   THEN 'Batch promotional'
        WHEN campaign_name LIKE 'TRG_EM_%' THEN 'Triggered journey'
        WHEN campaign_name IS NULL         THEN 'No attributed campaign'
        ELSE 'Other'
    END AS campaign_type,
    COUNT(*) AS buyers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM ATTRIBUTED
GROUP BY 1
ORDER BY 2 DESC
"""
    return client.execute_query(sql)


# ── Report generation ─────────────────────────────────────────────────────────

def fmt_table(rows: list[dict]) -> str:
    if not rows:
        return "_No data_\n"
    headers = list(rows[0].keys())
    col_widths = [max(len(str(h)), max((len(str(r.get(h, ""))) for r in rows), default=0)) for h in headers]
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    header_row = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    data_rows = [
        "| " + " | ".join(str(row.get(h, "")).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
        for row in rows
    ]
    return "\n".join([header_row, sep] + data_rows) + "\n"


def generate_report(
    send_list_profile,
    current_engagement,
    merch_pre_purchase,
    campaign_attribution,
    design_conversion,
    dormant_send_buckets,
    csv_path: Path,
    output_path: Path,
    csv_user_count: int = 0,
):
    today_str = TODAY.strftime("%B %d, %Y")
    ref_str   = COHORT_REF_DATE.strftime("%B %d, %Y")
    eng_start_str = ENGAGEMENT_START.strftime("%B %d, %Y")

    snowflake_cohort_size = sum(r.get("USERS", 0) or r.get("users", 0) for r in send_list_profile)
    csv_note = f"{csv_user_count:,} users in CSV" if csv_user_count else "CSV not provided"

    lines = [
        f"# HAV Pre-Converted Email Engagement Analysis",
        f"",
        f"**Generated:** {today_str}  ",
        f"**Source file:** `{csv_path.name}` ({csv_note})  ",
        f"**Snowflake cohort:** {snowflake_cohort_size:,} users emailed in last 90d, no design_fee, not unsubscribed  ",
        f"**Engagement window:** {eng_start_str} – {ref_str} (90 days)  ",
        f"**Conversion tracking:** {ref_str} – {today_str} (6 months forward)  ",
        f"",
        f"---",
        f"",
        f"## 1. Send List Composition",
        f"",
        f"Breakdown of the current pre-converted send list by lifecycle sub-stage.",
        f"(Merch purchases without a design fee purchase means they bought shop items directly.)",
        f"",
        fmt_table(send_list_profile),
        f"",
        f"---",
        f"",
        f"## 2. Current Email Engagement vs. Merch Purchase Rate",
        f"",
        f"Users classified by email engagement in the **trailing 90 days** (Jan 22 – Apr 22, 2026).  ",
        f"Merch rate = users who have ANY `merch_order_completed_fe` event (ever, not just recent).",
        f"",
        fmt_table(current_engagement),
        f"",
        f"---",
        f"",
        f"## 3. Email Touch Before a Merch Purchase",
        f"",
        f"For pre-converted merch buyers on this list: what was their email engagement",
        f"in the **90 days before their first merch purchase**?",
        f"",
        fmt_table(merch_pre_purchase),
        f"",
        f"---",
        f"",
        f"## 4. Last-Click Campaign Type Attribution (30-day window)",
        f"",
        f"For merch buyers, the campaign type of their last email click before purchase.",
        f"",
        fmt_table(campaign_attribution),
        f"",
        f"---",
        f"",
        f"## 5. Design Package Conversion by Email Engagement Tier (Cohort Analysis)",
        f"",
        f"**Cohort:** HAV pre-converted users who received at least one email between  ",
        f"{eng_start_str} and {ref_str} and had NOT yet purchased a design package.  ",
        f"",
        f"**Outcome:** Who subsequently paid the design fee within the following 6 months?",
        f"",
        fmt_table(design_conversion),
        f"",
        f"### Key Question: Does volume of sends to dormant users predict conversion?",
        f"",
        f"Among the dormant (no-open) cohort, broken down by how many emails they received:",
        f"",
        fmt_table(dormant_send_buckets),
        f"",
        f"---",
        f"",
        f"## Methodology Notes",
        f"",
        f"- **Dormant** = received ≥1 email in the window but zero human opens (machine opens excluded)",
        f"- **Merch purchase** = `merch_order_completed_fe` custom event in Braze, without a prior `design_fee` event",
        f"- **Design conversion** = `design_fee` or `design_fee_fe` event (paying for a design package)",
        f"- Machine opens filtered via `MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false'`",
        f"- Data source: Braze Raw Events Datashare (HAV workspace `{HAV}`)",
    ]
    report = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="HAV Pre-Converted Email Engagement Analysis")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Path to pre-converted export CSV (for record count only)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output report path")
    args = parser.parse_args()

    csv_path = args.csv
    csv_user_count = 0
    if csv_path.exists():
        print(f"Reading CSV for record count ({csv_path.name})...")
        _, csv_user_count = load_appboy_ids(csv_path)
        print(f"  {csv_user_count:,} users in CSV")
    else:
        print(f"Note: CSV not found at {csv_path} — using Snowflake-derived cohort only")

    print(f"Connecting to Snowflake...")
    client = get_snowflake_client(schema=SCHEMA, database=DB)

    print("Running Section 1: Send list composition (Snowflake-defined cohort)...")
    send_list_profile = query_send_list_profile(client)

    print("Running Section 2: Current engagement vs merch rate...")
    current_engagement = query_merch_email_attribution(client)

    print("Running Section 3: Email touch before merch purchase...")
    merch_pre_purchase = query_merch_purchase_profile(client)

    print("Running Section 4: Campaign attribution for merch buyers...")
    campaign_attribution = query_merch_by_campaign_type(client)

    print("Running Section 5: Design conversion cohort (this may take ~2 min)...")
    design_conversion = query_design_conversion_cohort(client)

    print("Running Section 5b: Dormant sub-breakdown by send volume...")
    dormant_send_buckets = query_design_conversion_by_send_count(client)

    print("Generating report...")
    report = generate_report(
        send_list_profile,
        current_engagement,
        merch_pre_purchase,
        campaign_attribution,
        design_conversion,
        dormant_send_buckets,
        csv_path,
        args.output,
        csv_user_count,
    )

    print(f"\n✓ Report written to: {args.output}")
    print("\n" + "=" * 60)
    # Print summary to stdout
    for line in report.split("\n")[:50]:
        print(line)


if __name__ == "__main__":
    main()

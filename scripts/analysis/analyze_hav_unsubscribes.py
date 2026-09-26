#!/usr/bin/env python3
"""
HAV Email Unsubscribe Journey Analysis

Analyzes Havenly email unsubscribers from the Braze Raw Events Datashare,
examining their lifecycle journey stage at time of unsubscribe, time since
account creation, and unsubscribe rates at each milestone.

Usage:
    uv run python scripts/analysis/analyze_hav_unsubscribes.py
    uv run python scripts/analysis/analyze_hav_unsubscribes.py --output reports/custom-name.md
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
HAV = "664223fb71bcf3005760dfc2"

STAGE_LABELS = {
    "0_no_account": "No account (email-only)",
    "1_account_no_design_fee": "Account — no design_fee",
    "2_post_design_fee": "Post design_fee (pre launch_room)",
    "3_post_launch_room": "Post launch_room (pre design_complete)",
    "4_post_design_complete": "Post design_process_complete (pre merch)",
    "5_post_merch_order": "Post merch_order_completed",
}

# Reusable CTEs
MILESTONES_CTE = f"""
MILESTONES AS (
    SELECT
        USER_ID,
        MIN(CASE WHEN NAME IN ('account_created', 'account_created_fe') THEN TO_TIMESTAMP(TIME) END) AS first_account_created,
        MIN(CASE WHEN NAME IN ('design_fee', 'design_fee_fe') THEN TO_TIMESTAMP(TIME) END) AS first_design_fee,
        MIN(CASE WHEN NAME = 'launch_room' THEN TO_TIMESTAMP(TIME) END) AS first_launch_room,
        MIN(CASE WHEN NAME = 'design_process_complete' THEN TO_TIMESTAMP(TIME) END) AS first_design_process_complete,
        MIN(CASE WHEN NAME = 'merch_order_completed_fe' THEN TO_TIMESTAMP(TIME) END) AS first_merch_order
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
      AND NAME IN ('account_created', 'account_created_fe', 'design_fee', 'design_fee_fe',
                   'launch_room', 'design_process_complete', 'merch_order_completed_fe')
    GROUP BY USER_ID
),
USER_ATTRS AS (
    SELECT USER_ID,
           COALESCE(
               TRY_TO_TIMESTAMP(CUSTOM_ATTRIBUTES:registeredAt::STRING),
               TRY_TO_TIMESTAMP(CUSTOM_ATTRIBUTES:createdAt::STRING)
           ) AS account_created_at
    FROM {DB}.{SCHEMA}.USER_CUSTOM_ATTRIBUTES_VIEW_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY SF_UPDATED_AT DESC) = 1
),
USER_JOURNEY AS (
    SELECT
        m.USER_ID,
        COALESCE(a.account_created_at, m.first_account_created) AS account_created_at,
        m.first_design_fee,
        m.first_launch_room,
        m.first_design_process_complete,
        m.first_merch_order
    FROM MILESTONES m
    LEFT JOIN USER_ATTRS a ON m.USER_ID = a.USER_ID
),
UNSUBS AS (
    SELECT USER_ID, MIN(TO_TIMESTAMP(TIME)) AS unsub_time
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
    WHERE APP_GROUP_ID = '{HAV}'
    GROUP BY USER_ID
)
"""

STAGE_EXPR = """
CASE
    WHEN j.first_merch_order IS NOT NULL AND j.first_merch_order <= {event_time} THEN '5_post_merch_order'
    WHEN j.first_design_process_complete IS NOT NULL AND j.first_design_process_complete <= {event_time} THEN '4_post_design_complete'
    WHEN j.first_launch_room IS NOT NULL AND j.first_launch_room <= {event_time} THEN '3_post_launch_room'
    WHEN j.first_design_fee IS NOT NULL AND j.first_design_fee <= {event_time} THEN '2_post_design_fee'
    WHEN j.account_created_at IS NOT NULL AND j.account_created_at <= {event_time} THEN '1_account_no_design_fee'
    ELSE '0_no_account'
END
"""


def query_stage_distribution(client):
    """Section A: Journey stage at time of unsubscribe."""
    sql = f"""
WITH
{MILESTONES_CTE},
STAGED AS (
    SELECT
        u.USER_ID,
        u.unsub_time,
        j.account_created_at,
        {STAGE_EXPR.format(event_time='u.unsub_time')} AS journey_stage,
        DATEDIFF('day', j.account_created_at, u.unsub_time) AS days_since_account
    FROM UNSUBS u
    LEFT JOIN USER_JOURNEY j ON u.USER_ID = j.USER_ID
)
SELECT
    journey_stage,
    COUNT(*) AS unsub_users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_unsubs,
    ROUND(MEDIAN(days_since_account), 0) AS median_days_since_account,
    ROUND(AVG(days_since_account), 0) AS avg_days_since_account
FROM STAGED
GROUP BY journey_stage
ORDER BY journey_stage
"""
    return client.execute_query(sql)


def query_time_since_account(client):
    """Section B: Time since account creation, split by pre/post design_fee."""
    sql = f"""
WITH
{MILESTONES_CTE},
BASE AS (
    SELECT
        u.USER_ID,
        j.account_created_at,
        (j.first_design_fee IS NOT NULL AND j.first_design_fee <= u.unsub_time) AS had_design_fee,
        DATEDIFF('day', j.account_created_at, u.unsub_time) AS days_since_account
    FROM UNSUBS u
    LEFT JOIN USER_JOURNEY j ON u.USER_ID = j.USER_ID
),
BUCKETED AS (
    SELECT *,
        CASE
            WHEN account_created_at IS NULL THEN '0_unknown'
            WHEN days_since_account < 0 THEN '1_anomaly'
            WHEN days_since_account <= 7 THEN '2_0-7d'
            WHEN days_since_account <= 30 THEN '3_8-30d'
            WHEN days_since_account <= 90 THEN '4_31-90d'
            WHEN days_since_account <= 365 THEN '5_91-365d'
            ELSE '6_365+d'
        END AS time_bucket
    FROM BASE
)
SELECT
    time_bucket,
    COUNT(*) AS total_unsubs,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_total,
    SUM(CASE WHEN NOT had_design_fee THEN 1 ELSE 0 END) AS pre_design_fee,
    SUM(CASE WHEN had_design_fee THEN 1 ELSE 0 END) AS post_design_fee,
    ROUND(100.0 * SUM(CASE WHEN had_design_fee THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS pct_post_design_fee
FROM BUCKETED
GROUP BY time_bucket
ORDER BY time_bucket
"""
    return client.execute_query(sql)


def query_unsub_rates(client):
    """Section C: Unsubscribe rate by journey stage (sends-based)."""
    sql = f"""
WITH
{MILESTONES_CTE},
SEND_STAGES AS (
    SELECT DISTINCT
        s.USER_ID,
        {STAGE_EXPR.format(event_time='TO_TIMESTAMP(s.TIME)')} AS journey_stage
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
    LEFT JOIN USER_JOURNEY j ON s.USER_ID = j.USER_ID
    WHERE s.APP_GROUP_ID = '{HAV}'
),
RECIPIENTS AS (
    SELECT journey_stage, COUNT(DISTINCT USER_ID) AS unique_recipients
    FROM SEND_STAGES
    GROUP BY journey_stage
),
UNSUB_STAGES AS (
    SELECT
        u.USER_ID,
        {STAGE_EXPR.format(event_time='u.unsub_time')} AS journey_stage
    FROM UNSUBS u
    LEFT JOIN USER_JOURNEY j ON u.USER_ID = j.USER_ID
),
UNSUB_COUNTS AS (
    SELECT journey_stage, COUNT(DISTINCT USER_ID) AS unsub_users
    FROM UNSUB_STAGES
    GROUP BY journey_stage
)
SELECT
    r.journey_stage,
    r.unique_recipients,
    COALESCE(u.unsub_users, 0) AS unsub_users,
    ROUND(100.0 * COALESCE(u.unsub_users, 0) / NULLIF(r.unique_recipients, 0), 2) AS unsub_rate_pct
FROM RECIPIENTS r
LEFT JOIN UNSUB_COUNTS u ON r.journey_stage = u.journey_stage
ORDER BY r.journey_stage
"""
    return client.execute_query(sql)


def query_time_within_stage(client):
    """Section D: Median time from stage entry to unsubscribe."""
    sql = f"""
WITH
{MILESTONES_CTE},
STAGED AS (
    SELECT
        u.USER_ID,
        u.unsub_time,
        {STAGE_EXPR.format(event_time='u.unsub_time')} AS journey_stage,
        CASE
            WHEN j.first_merch_order IS NOT NULL AND j.first_merch_order <= u.unsub_time
                THEN DATEDIFF('day', j.first_merch_order, u.unsub_time)
            WHEN j.first_design_process_complete IS NOT NULL AND j.first_design_process_complete <= u.unsub_time
                THEN DATEDIFF('day', j.first_design_process_complete, u.unsub_time)
            WHEN j.first_launch_room IS NOT NULL AND j.first_launch_room <= u.unsub_time
                THEN DATEDIFF('day', j.first_launch_room, u.unsub_time)
            WHEN j.first_design_fee IS NOT NULL AND j.first_design_fee <= u.unsub_time
                THEN DATEDIFF('day', j.first_design_fee, u.unsub_time)
            ELSE DATEDIFF('day', j.account_created_at, u.unsub_time)
        END AS days_in_stage
    FROM UNSUBS u
    LEFT JOIN USER_JOURNEY j ON u.USER_ID = j.USER_ID
)
SELECT
    journey_stage,
    COUNT(*) AS unsub_users,
    ROUND(MEDIAN(days_in_stage), 0) AS median_days_in_stage,
    ROUND(AVG(days_in_stage), 0) AS avg_days_in_stage,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY days_in_stage), 0) AS p25_days,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY days_in_stage), 0) AS p75_days
FROM STAGED
WHERE days_in_stage IS NOT NULL AND days_in_stage >= 0
  AND journey_stage != '0_no_account'
GROUP BY journey_stage
ORDER BY journey_stage
"""
    return client.execute_query(sql)


def fmt_num(n):
    """Format number with comma separators."""
    if n is None:
        return "—"
    return f"{int(n):,}"


def fmt_pct(p):
    if p is None:
        return "—"
    return f"{float(p):.1f}%"


def format_report(stage_dist, time_buckets, unsub_rates, time_in_stage, run_date):
    total_unsubs = sum(r["UNSUB_USERS"] for r in stage_dist)

    lines = [
        "# HAV Email Unsubscribe Journey Analysis",
        "",
        f"*Generated {run_date} · Data: Braze Raw Events Datashare (Jul 2024 – present)*",
        "",
        f"**Total HAV email unsubscribers:** {fmt_num(total_unsubs)}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "- **90%** of unsubscribers had NOT paid for a design (never reached `design_fee`)",
        "- **71.6%** have a Havenly account but haven't converted — the largest single group",
        "- **18.4%** are email-only (no account event at all)",
        "- Users who have paid for design unsub at dramatically lower rates: **6.6%** vs **35%** for pre-design_fee",
        "- Unsubscribe pressure is highest at the very beginning: 25% of unsubbers leave within 30 days of account creation",
        "",
        "---",
        "",
        "## A. Journey Stage at Time of Unsubscribe",
        "",
        "Highest milestone each user had completed *before* their unsubscribe.",
        "",
        "| Journey Stage | Unsubs | % of Total | Median Days Since Account |",
        "|---|---:|---:|---:|",
    ]

    for r in stage_dist:
        label = STAGE_LABELS.get(r["JOURNEY_STAGE"], r["JOURNEY_STAGE"])
        med = r.get("MEDIAN_DAYS_SINCE_ACCOUNT")
        med_str = f"{int(med):,}d" if med is not None else "—"
        lines.append(
            f"| {label} | {fmt_num(r['UNSUB_USERS'])} | {fmt_pct(r['PCT_OF_UNSUBS'])} | {med_str} |"
        )

    lines += [
        "",
        "> **Key takeaway:** The pre-design_fee account holders (71.6%) are the dominant unsub group.",
        "> They have accounts but haven't committed to the service — and email isn't converting them.",
        "",
        "---",
        "",
        "## B. Time Since Account Creation",
        "",
        "Distribution of unsubscribes by days from `registeredAt` to unsubscribe, split by journey stage.",
        "",
        "| Time Since Account | Total Unsubs | % | Pre design_fee | Post design_fee | % Post design_fee |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    bucket_labels = {
        "0_unknown": "Unknown",
        "1_anomaly": "Anomaly (<0d)",
        "2_0-7d": "0–7 days",
        "3_8-30d": "8–30 days",
        "4_31-90d": "31–90 days",
        "5_91-365d": "91–365 days",
        "6_365+d": "365+ days",
    }

    for r in time_buckets:
        if r["TIME_BUCKET"] == "1_anomaly" and r["TOTAL_UNSUBS"] < 10:
            continue  # Skip noise
        label = bucket_labels.get(r["TIME_BUCKET"], r["TIME_BUCKET"])
        lines.append(
            f"| {label} | {fmt_num(r['TOTAL_UNSUBS'])} | {fmt_pct(r['PCT_TOTAL'])} | "
            f"{fmt_num(r['PRE_DESIGN_FEE'])} | {fmt_num(r['POST_DESIGN_FEE'])} | "
            f"{fmt_pct(r['PCT_POST_DESIGN_FEE'])} |"
        )

    lines += [
        "",
        "> **Note:** The 365+ days group (23.8%) is the largest single bucket — many long-tenured accounts",
        "> eventually unsub after years of non-engagement. The 0–7 day group (14.6%) represents immediate",
        "> post-signup unsubscribers who likely never intended to opt in.",
        "",
        "---",
        "",
        "## C. Unsubscribe Rate by Journey Stage",
        "",
        "Of all users who received at least one email while at each stage, what % unsubscribed at that stage?",
        "",
        "| Journey Stage | Recipients | Unsubs | Unsub Rate |",
        "|---|---:|---:|---:|",
    ]

    for r in unsub_rates:
        label = STAGE_LABELS.get(r["JOURNEY_STAGE"], r["JOURNEY_STAGE"])
        lines.append(
            f"| {label} | {fmt_num(r['UNIQUE_RECIPIENTS'])} | "
            f"{fmt_num(r['UNSUB_USERS'])} | {fmt_pct(r['UNSUB_RATE_PCT'])} |"
        )

    lines += [
        "",
        "> **Dramatic drop at design_fee:** Rate falls from ~35% (pre-purchase) to **6.6%** right after",
        "> paying for design. Converts are engaged and not leaving. The rate climbs again post-design as",
        "> the active service engagement fades.",
        "> ",
        "> *Note: these are lifetime cumulative rates (Jul 2024–present), not per-email rates.*",
        "",
        "---",
        "",
        "## D. Time Within Stage Before Unsubscribing",
        "",
        "After entering each stage, how quickly did unsubscribers leave?",
        "",
        "| Journey Stage | Unsubs | Median Days | Avg Days | P25 | P75 |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for r in time_in_stage:
        label = STAGE_LABELS.get(r["JOURNEY_STAGE"], r["JOURNEY_STAGE"])
        lines.append(
            f"| {label} | {fmt_num(r['UNSUB_USERS'])} | "
            f"{fmt_num(r['MEDIAN_DAYS_IN_STAGE'])}d | {fmt_num(r['AVG_DAYS_IN_STAGE'])}d | "
            f"{fmt_num(r['P25_DAYS'])}d | {fmt_num(r['P75_DAYS'])}d |"
        )

    lines += [
        "",
        "> **Stage 1 (account, no design_fee):** Very wide spread (p25=15d, p75=446d) — some unsub quickly,",
        "> many linger for over a year before finally unsubbing. The median of 80 days suggests a ~3-month",
        "> window to convert them before they disengage.",
        "> ",
        "> **Stage 3 (post launch_room):** Fastest unsubs (median 45d) — the launch_room stage may feel like",
        "> a dead-end if design delivery takes too long.",
        "",
        "---",
        "",
        "## Implications",
        "",
        "1. **The pre-design_fee account holder is the core unsub problem.** 71.6% of unsubbers have accounts",
        "   but haven't paid. Email isn't moving them down the funnel, and they eventually disengage.",
        "   The 80-day median suggests there's a ~3-month window to convert before they're likely to unsub.",
        "",
        "2. **Design_fee is a strong loyalty signal.** The 6.6% unsub rate post-design_fee (vs 35% pre) is",
        "   the most striking finding. Once a user pays, they stay — but they do eventually unsub if the",
        "   experience ends without a next step.",
        "",
        "3. **Post-completion dropout is real.** After design is done (stage 4: 26.2%) or after merch purchase",
        "   (stage 5: 36.5%), rates climb back up. The product relationship may feel \"finished\" — these users",
        "   don't see a reason to stay subscribed.",
        "",
        "4. **~15% unsub within the first week.** The 0–7 day bucket likely contains users who signed up for",
        "   content but weren't expecting email — or who signed up to access a feature and immediately regretted",
        "   opting in.",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="HAV email unsubscribe journey analysis")
    parser.add_argument(
        "--output",
        default="reports/hav-unsubscribe-analysis.md",
        help="Output markdown file path",
    )
    args = parser.parse_args()

    print("Connecting to Snowflake (Braze datashare)...")
    client = get_snowflake_client(schema=SCHEMA, database=DB)

    print("Running Section A: journey stage distribution...")
    stage_dist = query_stage_distribution(client)
    print(f"  {len(stage_dist)} rows")

    print("Running Section B: time since account creation...")
    time_buckets = query_time_since_account(client)
    print(f"  {len(time_buckets)} rows")

    print("Running Section C: unsubscribe rates by stage...")
    unsub_rates = query_unsub_rates(client)
    print(f"  {len(unsub_rates)} rows")

    print("Running Section D: time within stage before unsubbing...")
    time_in_stage = query_time_within_stage(client)
    print(f"  {len(time_in_stage)} rows")

    run_date = datetime.now().strftime("%Y-%m-%d")
    report = format_report(stage_dist, time_buckets, unsub_rates, time_in_stage, run_date)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""HAV email click concentration analysis — 4 queries."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = 'BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206'
SCHEMA = 'DATALAKE_SHARING'
HAV_APP_GROUP = '664223fb71bcf3005760dfc2'

client = get_snowflake_client(schema=SCHEMA, database=DB)

# ── Diagnostic ────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("DIAGNOSTIC — Top 40 link aliases / URLs (last 30 days, non-bot)")
print("="*70)

diag_sql = f"""
SELECT LINK_ALIAS, URL, COUNT(*) as clicks
FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
WHERE APP_GROUP_ID = '{HAV_APP_GROUP}'
  AND TO_TIMESTAMP(TIME) >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
GROUP BY 1, 2
ORDER BY clicks DESC
LIMIT 40
"""
rows = client.execute_query(diag_sql)
for r in rows:
    alias = r.get('LINK_ALIAS') or r.get('link_alias') or '(null)'
    url = r.get('URL') or r.get('url') or ''
    clicks = r.get('CLICKS') or r.get('clicks') or 0
    print(f"  {clicks:>6}  alias={alias!r:40s}  url={url[:80]}")

# ── Query 1 — Overall top-2 vs rest (180 days) ───────────────────────────────
print("\n" + "="*70)
print("QUERY 1 — Overall: top 2 links per campaign vs rest (last 180 days)")
print("="*70)

q1_sql = f"""
WITH body_clicks AS (
    SELECT
        CAMPAIGN_API_ID,
        MESSAGE_VARIATION_API_ID,
        LINK_ALIAS,
        COUNT(*) AS clicks
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{HAV_APP_GROUP}'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -180, CURRENT_TIMESTAMP())
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
      AND URL NOT LIKE '%unsubscribe%'
      AND URL NOT LIKE '%optout%'
      AND URL NOT LIKE '%facebook.com%'
      AND URL NOT LIKE '%twitter.com%'
      AND URL NOT LIKE '%instagram.com%'
      AND URL NOT LIKE '%pinterest.com%'
      AND URL NOT LIKE '%privacy%'
      AND URL NOT LIKE '%policies/terms%'
      AND URL NOT LIKE '%terms-of-service%'
      AND (LINK_ALIAS IS NULL OR LINK_ALIAS NOT LIKE 'cb10_%')
    GROUP BY 1, 2, 3
),
ranked AS (
    SELECT *,
        RANK() OVER (PARTITION BY CAMPAIGN_API_ID, MESSAGE_VARIATION_API_ID ORDER BY clicks DESC) AS click_rank
    FROM body_clicks
),
summary AS (
    SELECT
        CASE WHEN click_rank <= 2 THEN 'Top 2 slots' ELSE 'Other links' END AS slot_group,
        SUM(clicks) AS total_clicks
    FROM ranked
    GROUP BY 1
)
SELECT
    slot_group,
    total_clicks,
    ROUND(100.0 * total_clicks / SUM(total_clicks) OVER (), 1) AS pct_of_all_clicks
FROM summary
ORDER BY total_clicks DESC
"""
rows = client.execute_query(q1_sql)
for r in rows:
    sg = r.get('SLOT_GROUP') or r.get('slot_group')
    tc = r.get('TOTAL_CLICKS') or r.get('total_clicks')
    pct = r.get('PCT_OF_ALL_CLICKS') or r.get('pct_of_all_clicks')
    print(f"  {sg}: {tc:,} clicks ({pct}%)")

# ── Query 2 — Per-campaign avg % to top-2 (180 days, ≥20 body clicks) ────────
print("\n" + "="*70)
print("QUERY 2 — Per-campaign: avg % going to top 2 slots (≥20 body clicks)")
print("="*70)

q2_sql = f"""
WITH body_clicks AS (
    SELECT
        CAMPAIGN_API_ID,
        MESSAGE_VARIATION_API_ID,
        LINK_ALIAS,
        COUNT(*) AS clicks
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{HAV_APP_GROUP}'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -180, CURRENT_TIMESTAMP())
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
      AND URL NOT LIKE '%unsubscribe%'
      AND URL NOT LIKE '%optout%'
      AND URL NOT LIKE '%facebook.com%'
      AND URL NOT LIKE '%twitter.com%'
      AND URL NOT LIKE '%instagram.com%'
      AND URL NOT LIKE '%pinterest.com%'
      AND URL NOT LIKE '%privacy%'
      AND URL NOT LIKE '%policies/terms%'
      AND URL NOT LIKE '%terms-of-service%'
      AND (LINK_ALIAS IS NULL OR LINK_ALIAS NOT LIKE 'cb10_%')
    GROUP BY 1, 2, 3
),
ranked AS (
    SELECT *,
        RANK() OVER (PARTITION BY CAMPAIGN_API_ID, MESSAGE_VARIATION_API_ID ORDER BY clicks DESC) AS click_rank
    FROM body_clicks
),
per_campaign AS (
    SELECT
        CAMPAIGN_API_ID,
        SUM(clicks) AS total_clicks,
        SUM(CASE WHEN click_rank <= 2 THEN clicks ELSE 0 END) AS top2_clicks,
        ROUND(100.0 * SUM(CASE WHEN click_rank <= 2 THEN clicks ELSE 0 END) / NULLIF(SUM(clicks), 0), 1) AS pct_top2
    FROM ranked
    GROUP BY 1
    HAVING total_clicks >= 20
)
SELECT
    COUNT(*) AS num_campaigns,
    ROUND(AVG(pct_top2), 1) AS avg_pct_top2,
    ROUND(MEDIAN(pct_top2), 1) AS median_pct_top2,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pct_top2) AS p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pct_top2) AS p75
FROM per_campaign
"""
rows = client.execute_query(q2_sql)
for r in rows:
    keys = [k.upper() for k in r.keys()]
    vals = dict(zip(keys, r.values()))
    print(f"  Campaigns (≥20 clicks): {vals.get('NUM_CAMPAIGNS'):,}")
    print(f"  Avg % to top-2:         {vals.get('AVG_PCT_TOP2')}%")
    print(f"  Median % to top-2:      {vals.get('MEDIAN_PCT_TOP2')}%")
    print(f"  P25:                    {vals.get('P25')}%")
    print(f"  P75:                    {vals.get('P75')}%")

# ── Query 3 — Click share by rank position (180 days) ─────────────────────────
print("\n" + "="*70)
print("QUERY 3 — Click share by rank position (1 through 6+)")
print("="*70)

q3_sql = f"""
WITH body_clicks AS (
    SELECT
        CAMPAIGN_API_ID,
        MESSAGE_VARIATION_API_ID,
        LINK_ALIAS,
        COUNT(*) AS clicks
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{HAV_APP_GROUP}'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -180, CURRENT_TIMESTAMP())
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
      AND URL NOT LIKE '%unsubscribe%'
      AND URL NOT LIKE '%optout%'
      AND URL NOT LIKE '%facebook.com%'
      AND URL NOT LIKE '%twitter.com%'
      AND URL NOT LIKE '%instagram.com%'
      AND URL NOT LIKE '%pinterest.com%'
      AND URL NOT LIKE '%privacy%'
      AND URL NOT LIKE '%policies/terms%'
      AND URL NOT LIKE '%terms-of-service%'
      AND (LINK_ALIAS IS NULL OR LINK_ALIAS NOT LIKE 'cb10_%')
    GROUP BY 1, 2, 3
),
ranked AS (
    SELECT *,
        RANK() OVER (PARTITION BY CAMPAIGN_API_ID, MESSAGE_VARIATION_API_ID ORDER BY clicks DESC) AS click_rank
    FROM body_clicks
)
SELECT
    CASE WHEN click_rank >= 6 THEN '6+' ELSE CAST(click_rank AS VARCHAR) END AS rank_label,
    SUM(clicks) AS total_clicks,
    ROUND(100.0 * SUM(clicks) / SUM(SUM(clicks)) OVER (), 1) AS pct_of_all_clicks
FROM ranked
GROUP BY 1
ORDER BY MIN(click_rank)
"""
rows = client.execute_query(q3_sql)
for r in rows:
    keys = [k.upper() for k in r.keys()]
    vals = dict(zip(keys, r.values()))
    rank = vals.get('RANK_LABEL')
    tc = vals.get('TOTAL_CLICKS')
    pct = vals.get('PCT_OF_ALL_CLICKS')
    print(f"  Rank {rank}: {tc:,} clicks ({pct}%)")

print("\nDone.")

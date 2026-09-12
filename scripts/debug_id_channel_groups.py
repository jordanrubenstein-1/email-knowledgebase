#!/usr/bin/env python3
"""Debug: Check ID January 2026 campaigns - compare Email vs other channel groups."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import sys
sys.path.insert(0, str(Path(__file__).parent))
from snowflake_client import get_snowflake_client

schema = "LANDING_INTERIORDEFINE_GA4"
table = "TRAFFIC_SESSION_PERFORMANCE_DAILY"
database = os.environ.get("SNOWFLAKE_DATABASE")
full_table = f"{database}.{schema}.{table}"

# Query for all ID campaigns starting with P_EM_2026_01 (January 2026 emails)
# Group by campaign name and channel group to see misattribution
query = f"""
SELECT 
    SESSIONCAMPAIGNNAME,
    SESSIONPRIMARYCHANNELGROUP,
    SUM(SESSIONS) as sessions,
    SUM(ECOMMERCEPURCHASES) as purchases,
    SUM(TOTALREVENUE) as revenue
FROM {full_table}
WHERE SESSIONCAMPAIGNNAME LIKE 'P_EM_2026_01%'
  AND SESSIONCAMPAIGNNAME LIKE '%ID%'
  AND DATE >= '20260101' AND DATE <= '20260210'
GROUP BY SESSIONCAMPAIGNNAME, SESSIONPRIMARYCHANNELGROUP
ORDER BY SESSIONCAMPAIGNNAME, sessions DESC
"""

print("Querying Snowflake for ID January 2026 email campaigns by channel group...")
print(f"Table: {full_table}")
print()

client = get_snowflake_client(schema=schema)
rows = client.execute_query(query, None)

# Group by campaign name
campaigns = {}
for row in rows:
    name = row['SESSIONCAMPAIGNNAME']
    if name not in campaigns:
        campaigns[name] = []
    campaigns[name].append(row)

# Find campaigns with non-Email channel groups that have significant sessions/revenue
print(f"Found {len(campaigns)} unique campaigns\n")
print("=" * 80)
print("Campaigns with sessions/revenue in NON-Email channel groups:")
print("=" * 80)

misattributed = []
for name, rows in sorted(campaigns.items()):
    non_email = [r for r in rows if r['SESSIONPRIMARYCHANNELGROUP'] not in ('Email', 'SMS')]
    email = [r for r in rows if r['SESSIONPRIMARYCHANNELGROUP'] == 'Email']
    
    non_email_sessions = sum(r['SESSIONS'] for r in non_email)
    non_email_revenue = sum(r['REVENUE'] or 0 for r in non_email)
    email_sessions = sum(r['SESSIONS'] for r in email)
    email_revenue = sum(r['REVENUE'] or 0 for r in email)
    
    if non_email_sessions > 0 or non_email_revenue > 0:
        misattributed.append({
            'name': name,
            'email_sessions': email_sessions,
            'email_revenue': email_revenue,
            'non_email_sessions': non_email_sessions,
            'non_email_revenue': non_email_revenue,
            'channels': [r['SESSIONPRIMARYCHANNELGROUP'] for r in non_email]
        })

# Sort by non-email revenue descending
misattributed.sort(key=lambda x: x['non_email_revenue'], reverse=True)

for m in misattributed:
    print(f"\n{m['name']}")
    print(f"  Email channel:     {m['email_sessions']:,} sessions, ${m['email_revenue']:,.2f} revenue")
    print(f"  Non-Email channel: {m['non_email_sessions']:,} sessions, ${m['non_email_revenue']:,.2f} revenue")
    print(f"  Channel groups: {set(m['channels'])}")

print(f"\n\n{'=' * 80}")
print(f"SUMMARY: {len(misattributed)} of {len(campaigns)} campaigns have non-Email attributed sessions/revenue")
total_non_email_rev = sum(m['non_email_revenue'] for m in misattributed)
total_email_rev = sum(m['email_revenue'] for m in misattributed)
print(f"Total non-Email revenue: ${total_non_email_rev:,.2f}")
print(f"Total Email revenue (for those same campaigns): ${total_email_rev:,.2f}")

client.close()

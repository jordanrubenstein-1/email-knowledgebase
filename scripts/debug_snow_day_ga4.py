#!/usr/bin/env python3
"""Debug: Query Snowflake for Snow_Day_Shopping campaign to see why it's not matching."""

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

# Query for campaigns with "Snow_Day" in name around 1/26
query = f"""
SELECT 
    SESSIONCAMPAIGNNAME,
    SESSIONPRIMARYCHANNELGROUP,
    SUM(SESSIONS) as sessions,
    SUM(ECOMMERCEPURCHASES) as purchases,
    SUM(TOTALREVENUE) as revenue
FROM {full_table}
WHERE SESSIONCAMPAIGNNAME LIKE '%Snow_Day%'
   OR SESSIONCAMPAIGNNAME LIKE '%Winter_Retreat_Sale_Snow%'
GROUP BY SESSIONCAMPAIGNNAME, SESSIONPRIMARYCHANNELGROUP
ORDER BY sessions DESC
"""

print("Querying Snowflake for Snow_Day campaigns...")
print(f"Table: {full_table}")
print()

client = get_snowflake_client(schema=schema)
rows = client.execute_query(query, None)

print(f"Found {len(rows)} rows:\n")
for row in rows:
    print(row)

client.close()

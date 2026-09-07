"""
ID Designed Email — User-level click overlap (8/9-8/22/2026)
================================================================
Extends id_link_position_analysis.py: instead of counting click EVENTS (which
double-counts a user who clicks multiple links), this pulls distinct
(campaign, user, link) triples so we can classify each CLICKING USER by
whether their engagement would survive a content cut:

  - "kept-only"  : every link they clicked is in the kept set (hero-or-above,
                   main CTA/kicker, or footer) -> unaffected by a cut
  - "both"       : they clicked kept content AND cuttable content -> if we cut
                   the cuttable content, this user still shows up as engaged
                   (their click on the kept content survives)
  - "cut-only"   : every link they clicked is in the cuttable set -> cutting
                   that content loses this user's engagement entirely

Read-only.
"""

import json
import sys

sys.path.insert(0, ".")
from scripts.snowflake_client import get_snowflake_client

TIER3_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
TIER3_SCHEMA = "DATALAKE_SHARING_TIERED"
ID_APP_GROUP = "6666726b459b5e0059d7d687"

CAMPAIGNS = {
    "2026-08-09": "88c244b2-979b-4cb9-8d5b-dacea9df0bb9",
    "2026-08-10": "b3b06dfc-4669-4686-8b20-32efaf3cf8ff",
    "2026-08-12": "1e198c70-6027-4be2-a02c-239bd5ac6ca8",
    "2026-08-13": "76576e13-bc39-490c-b266-000f1d63d2af",
    "2026-08-14": "ef31f263-b42b-4c46-b531-369038bfaad6",
    "2026-08-15": "ba13894d-8626-4250-bc08-f164f3fdf378",
    "2026-08-16": "acc0c3dd-3364-48e1-a7af-11f18dd51ef5",
    "2026-08-17": "bd4bb336-dbd8-46af-975b-d6fff17474e1",
    "2026-08-18": "a20ddbb1-77dd-4d63-b033-700428e4d89b",
    "2026-08-19": "1ca95759-1039-4cac-add2-cec65715479f",
    "2026-08-20a": "953b6923-e538-4b02-a537-8a7752851566",
    "2026-08-20b": "d2a3a92c-086d-45f2-9287-f4092ae02e35",
    "2026-08-21": "a23825e8-eacc-4eba-856b-54bdc3712943",
    "2026-08-22": "1c2c2c09-d475-4393-afda-5c427e890604",
}

api_id_list_sql = ", ".join(f"'{a}'" for a in CAMPAIGNS.values())

QUERY = f"""
SELECT DISTINCT
    e.CAMPAIGN_API_ID,
    e.USER_ID,
    e.LINK_ID
FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
WHERE e.APP_GROUP_ID = '{ID_APP_GROUP}'
  AND e.CAMPAIGN_API_ID IN ({api_id_list_sql})
  AND (e.IS_SUSPECTED_BOT_CLICK IS NULL OR e.IS_SUSPECTED_BOT_CLICK = 'false')
  AND e.URL NOT ILIKE '%unsubscribe%'
  AND e.LINK_ID IS NOT NULL
"""


def main():
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    rows = client.execute_query(QUERY)

    by_campaign = {}
    for r in rows:
        cid = r["CAMPAIGN_API_ID"]
        by_campaign.setdefault(cid, []).append({"user_id": r["USER_ID"], "link_id": r["LINK_ID"]})

    out_path = "/private/tmp/claude-501/-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/7fbfd7b8-510f-4d6e-b02f-045684cb6eaf/scratchpad/id_link_user_clicks.json"
    with open(out_path, "w") as f:
        json.dump(by_campaign, f, indent=2)

    print(f"Wrote {out_path}")
    for date, api_id in CAMPAIGNS.items():
        rows_for_camp = by_campaign.get(api_id, [])
        distinct_users = len({r["user_id"] for r in rows_for_camp})
        print(f"  {date}  api_id={api_id}  user_link_rows={len(rows_for_camp)}  distinct_users={distinct_users}")


if __name__ == "__main__":
    main()

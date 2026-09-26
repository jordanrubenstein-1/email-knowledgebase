"""
ID Designed Email — Link Click Position Analysis (8/9-8/22/2026)
==================================================================
Pulls per-link click counts for 13 ID designed (non-PT, non-Trade) campaigns
sent 2026-08-09 through 2026-08-22, for cross-reference against a manually
labeled slice/link-position spreadsheet. Read-only.

Output: JSON dict {campaign_api_id: [{link_id, link_alias, url, clicks}, ...]}
written to the scratchpad, plus a per-campaign total-clicks summary printed
to stdout for reconciliation against each campaign's YAML performance_summary.
"""

import json
import sys

sys.path.insert(0, ".")
from scripts.snowflake_client import get_snowflake_client

TIER3_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
TIER3_SCHEMA = "DATALAKE_SHARING_TIERED"
ID_APP_GROUP = "6666726b459b5e0059d7d687"

# date -> (campaign name, api id) for the 13 confirmed in-scope campaigns
CAMPAIGNS = {
    "2026-08-09": ("P_EM_2026_08_09_ID_PC_D_Swatch_Talk", "88c244b2-979b-4cb9-8d5b-dacea9df0bb9"),
    "2026-08-10": ("P_EM_2026_08_10_ID_PC_D_Flash_Sale_James_Collection", "b3b06dfc-4669-4686-8b20-32efaf3cf8ff"),
    "2026-08-12": ("P_EM_2026_08_12_ID_PC_D_Flash_Sale_Reminder", "1e198c70-6027-4be2-a02c-239bd5ac6ca8"),
    "2026-08-13": ("P_EM_2026_08_13_ID_PC_D_Accent_Seating", "76576e13-bc39-490c-b266-000f1d63d2af"),
    "2026-08-14": ("P_EM_2026_08_14_ID_PC_D_Tatum_Collection", "ef31f263-b42b-4c46-b531-369038bfaad6"),
    "2026-08-15": ("P_EM_2026_08_15_ID_PC_D_Beds_Feature", "ba13894d-8626-4250-bc08-f164f3fdf378"),
    "2026-08-16": ("P_EM_2026_08_16_ID_D_PR_Rug_Round_Up", "acc0c3dd-3364-48e1-a7af-11f18dd51ef5"),
    "2026-08-17": ("P_EM_2026_08_17_ID_PC_D_Swatch_Talk_Leather", "bd4bb336-dbd8-46af-975b-d6fff17474e1"),
    "2026-08-18": ("P_EM_2026_08_18_ID_PC_D_Labor_Day_EA_Launch_AM", "a20ddbb1-77dd-4d63-b033-700428e4d89b"),
    "2026-08-19": ("P_EM_2026_08_19_ID_PC_D_Labor_Day_Sale_Instore_Callout", "1ca95759-1039-4cac-add2-cec65715479f"),
    "2026-08-20a": ("P_EM_2026_08_20_ID_PC_D_Labor_Day_Launch", "953b6923-e538-4b02-a537-8a7752851566"),
    "2026-08-20b": ("P_EM_2026_08_20_ID_PC_D_Cyrus_Collection", "d2a3a92c-086d-45f2-9287-f4092ae02e35"),
    "2026-08-21": ("P_EM_2026_08_21_ID_PC_D_Labor_Day_Sale_Store_Callout", "a23825e8-eacc-4eba-856b-54bdc3712943"),
    "2026-08-22": ("P_EM_2026_08_22_ID_PC_D_Living_Room_Edit_PM", "1c2c2c09-d475-4393-afda-5c427e890604"),
}

api_ids = [v[1] for v in CAMPAIGNS.values()]
api_id_list_sql = ", ".join(f"'{a}'" for a in api_ids)

QUERY = f"""
SELECT
    e.CAMPAIGN_API_ID,
    e.LINK_ID,
    e.LINK_ALIAS,
    e.URL,
    COUNT(*) AS clicks
FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
WHERE e.APP_GROUP_ID = '{ID_APP_GROUP}'
  AND e.CAMPAIGN_API_ID IN ({api_id_list_sql})
  AND (e.IS_SUSPECTED_BOT_CLICK IS NULL OR e.IS_SUSPECTED_BOT_CLICK = 'false')
  AND e.URL NOT ILIKE '%unsubscribe%'
GROUP BY 1, 2, 3, 4
ORDER BY e.CAMPAIGN_API_ID, clicks DESC
"""


def main():
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    rows = client.execute_query(QUERY)

    by_campaign = {}
    for r in rows:
        cid = r["CAMPAIGN_API_ID"]
        by_campaign.setdefault(cid, []).append(
            {
                "link_id": r["LINK_ID"],
                "link_alias": r["LINK_ALIAS"],
                "url": r["URL"],
                "clicks": r["CLICKS"],
            }
        )

    out_path = "/private/tmp/claude-501/-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/7fbfd7b8-510f-4d6e-b02f-045684cb6eaf/scratchpad/id_link_clicks.json"
    with open(out_path, "w") as f:
        json.dump(by_campaign, f, indent=2)

    print(f"Wrote {out_path}")
    print()
    print("Per-campaign click totals (for reconciliation vs YAML performance_summary):")
    for date, (name, api_id) in CAMPAIGNS.items():
        links = by_campaign.get(api_id, [])
        total = sum(l["clicks"] for l in links)
        print(f"  {date}  {name}  api_id={api_id}  matched_links={len(links)}  total_clicks={total}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Set june_2026_second_room_cohort = true on HAV users who:
  - ORDER_LTV_SIX_MONTH > $2,000
  - LAST_ROOM_COMPLETED_AT within last 26 weeks
  - Found in Braze (by EXTERNAL_USER_ID match)
  - Have never unsubscribed

Uses braze_id (internal Braze ID) — never creates new profiles.
Batches of 75 per /users/track call (Braze limit).
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.snowflake_client import get_snowflake_client

load_dotenv()

BRAZE_API_KEY = os.environ["BRAZE_API_KEY_HAV_USERS"]
BRAZE_URL = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"
ATTRIBUTE_NAME = "june_2026_second_room_cohort"
BATCH_SIZE = 75
DRY_RUN = "--dry-run" in sys.argv


def fetch_braze_ids():
    client = get_snowflake_client(schema="DATALAKE_SHARING",
                                  database="BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206")
    query = f"""
    WITH target_users AS (
      SELECT CAST(USER_ID AS VARCHAR) AS user_id_str
      FROM PROD.ANALYTICS.USER_FACTS
      WHERE ORDER_LTV_SIX_MONTH > 2000
        AND LAST_ROOM_COMPLETED_AT >= DATEADD('week', -26, CURRENT_DATE())
    ),
    braze_users AS (
      SELECT t.user_id_str, u.USER_ID AS braze_user_id
      FROM target_users t
      JOIN BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206.DATALAKE_SHARING.USER_DEFAULT_ATTRIBUTES_VIEW_SHARED u
        ON u.EXTERNAL_USER_ID = t.user_id_str
        AND u.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
    ),
    unsubbed AS (
      SELECT DISTINCT USER_ID
      FROM BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206.DATALAKE_SHARING.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
      WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
    )
    SELECT DISTINCT b.braze_user_id
    FROM braze_users b
    LEFT JOIN unsubbed u ON b.braze_user_id = u.USER_ID
    WHERE u.USER_ID IS NULL
    """
    rows = client.execute_query(query)
    return [r["BRAZE_USER_ID"] for r in rows]


def set_attribute_batch(braze_ids: list[str]) -> dict:
    payload = {
        "attributes": [
            {"braze_id": bid, ATTRIBUTE_NAME: True}
            for bid in braze_ids
        ]
    }
    resp = requests.post(
        f"{BRAZE_URL}/users/track",
        headers={
            "Authorization": f"Bearer {BRAZE_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"Fetching target user list from Snowflake...")
    braze_ids = fetch_braze_ids()
    print(f"Found {len(braze_ids)} sendable users to tag")

    if DRY_RUN:
        print(f"[DRY RUN] Would set {ATTRIBUTE_NAME}=true on {len(braze_ids)} users in {-(-len(braze_ids) // BATCH_SIZE)} batches")
        print(f"[DRY RUN] Sample braze_ids: {braze_ids[:3]}")
        return

    total = len(braze_ids)
    success_count = 0
    error_count = 0

    for i in range(0, total, BATCH_SIZE):
        batch = braze_ids[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = -(-total // BATCH_SIZE)

        try:
            result = set_attribute_batch(batch)
            errors = result.get("errors", [])
            if errors:
                print(f"  Batch {batch_num}/{total_batches}: {len(batch) - len(errors)} ok, {len(errors)} errors — {errors}")
                error_count += len(errors)
                success_count += len(batch) - len(errors)
            else:
                print(f"  Batch {batch_num}/{total_batches}: {len(batch)} ok")
                success_count += len(batch)
        except Exception as e:
            print(f"  Batch {batch_num}/{total_batches}: FAILED — {e}")
            error_count += len(batch)

        if i + BATCH_SIZE < total:
            time.sleep(0.25)  # stay well under rate limit

    print(f"\nDone. {success_count} users tagged, {error_count} errors.")


if __name__ == "__main__":
    main()

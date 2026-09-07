#!/usr/bin/env python3
"""
Sync Havenly style-quiz zip codes to Braze user profiles.

Queries PROD.ANALYTICS.USER_FACTS for users with ONBOARDING_ANSWER_HOME_ZIP_CODE
and writes `zipCode` as a Braze custom attribute via /users/track.

Only syncs users who don't already have a zipCode in Braze (purchase zip takes
priority — this script never overwrites an existing value). Incremental by
default: looks at users created in the last 2 days. Use --full for the initial
backfill of all ~393K users with an onboarding zip.

Usage:
  uv run python scripts/sync_hav_zip_codes.py              # last 2 days (default)
  uv run python scripts/sync_hav_zip_codes.py --days 7     # last 7 days
  uv run python scripts/sync_hav_zip_codes.py --full       # all-time initial backfill
  uv run python scripts/sync_hav_zip_codes.py --dry-run    # preview only
"""

import argparse
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.snowflake_client import get_snowflake_client

BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY_HAV_USERS") or os.environ.get("BRAZE_API_KEY_HAV")
BRAZE_BASE_URL = os.environ.get("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com").rstrip("/")
BATCH_SIZE = 75  # Braze /users/track limit per request
HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"


def fetch_zip_codes(days: int | None) -> list[dict]:
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")

    date_filter = (
        f"AND uf.USER_CREATED >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())"
        if days is not None else ""
    )

    # Only pull users who:
    #   1. exist in Braze already (to avoid creating ghost profiles)
    #   2. don't already have zipCode (purchase zip takes priority)
    query = f"""
        WITH braze_exists AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206.DATALAKE_SHARING.USERS_MESSAGES_EMAIL_SEND_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
        ),
        braze_has_zip AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206.DATALAKE_SHARING.USER_CUSTOM_ATTRIBUTES_VIEW_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND CUSTOM_ATTRIBUTES:zipCode IS NOT NULL
              AND CUSTOM_ATTRIBUTES:zipCode != ''
        )
        SELECT
            uf.USER_ID::STRING AS user_id,
            uf.ONBOARDING_ANSWER_HOME_ZIP_CODE AS zip_code
        FROM PROD.ANALYTICS.USER_FACTS uf
        INNER JOIN braze_exists be ON uf.USER_ID::STRING = be.EXTERNAL_USER_ID
        LEFT JOIN braze_has_zip bz ON uf.USER_ID::STRING = bz.EXTERNAL_USER_ID
        WHERE uf.ONBOARDING_ANSWER_HOME_ZIP_CODE IS NOT NULL
          AND bz.EXTERNAL_USER_ID IS NULL   -- not already in Braze
          {date_filter}
    """
    rows = client.execute_query(query)
    return [{"user_id": r["USER_ID"], "zip_code": r["ZIP_CODE"]} for r in rows]


def push_to_braze(batch: list[dict], dry_run: bool) -> int:
    attributes = [
        {"external_id": r["user_id"], "zipCode": r["zip_code"]}
        for r in batch
    ]
    if dry_run:
        for attr in attributes[:3]:
            print(f"  [dry-run] {attr}")
        if len(attributes) > 3:
            print(f"  [dry-run] ... and {len(attributes) - 3} more")
        return len(attributes)

    resp = requests.post(
        f"{BRAZE_BASE_URL}/users/track",
        headers={
            "Authorization": f"Bearer {BRAZE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"attributes": attributes},
        timeout=30,
    )
    if resp.status_code == 429:
        print("  Rate limited — waiting 60s")
        time.sleep(60)
        return push_to_braze(batch, dry_run)
    resp.raise_for_status()
    result = resp.json()
    errors = result.get("errors", [])
    if errors:
        print(f"  Braze errors: {errors}")
    return result.get("attributes_processed", len(attributes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2,
                        help="Lookback window in days by USER_CREATED (default: 2).")
    parser.add_argument("--full", action="store_true",
                        help="Full sync — all users with an onboarding zip not yet in Braze.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Braze.")
    args = parser.parse_args()

    if not BRAZE_API_KEY:
        print("ERROR: BRAZE_API_KEY_HAV_USERS (or BRAZE_API_KEY_HAV) not set", file=sys.stderr)
        sys.exit(1)

    days = None if args.full else args.days
    label = "all-time" if args.full else f"last {days} days"
    print(f"Fetching HAV users with onboarding zip not yet in Braze ({label})...")

    users = fetch_zip_codes(days)
    print(f"Found {len(users)} users to update")

    if not users:
        print("Nothing to sync.")
        return

    total = 0
    for i in range(0, len(users), BATCH_SIZE):
        batch = users[i:i + BATCH_SIZE]
        processed = push_to_braze(batch, args.dry_run)
        total += processed
        print(f"  Batch {i // BATCH_SIZE + 1}: {processed} attributes written")
        if not args.dry_run and i + BATCH_SIZE < len(users):
            time.sleep(0.5)  # stay under Braze rate limit

    action = "would update" if args.dry_run else "updated"
    print(f"Done — {action} {total} Braze profiles with zipCode")


if __name__ == "__main__":
    main()

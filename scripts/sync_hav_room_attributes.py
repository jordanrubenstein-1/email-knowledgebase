#!/usr/bin/env python3
"""
Sync Havenly room attributes to Braze user profiles.

Queries PROD.ANALYTICS.ROOM_DIMS for recent concept deliveries and writes
`concept_room_id` as a Braze custom attribute via /users/track.

This powers the Concept Ready lifecycle email without API trigger properties:
  CTA URL: https://havenly.com/room/home/{{custom_attribute.${concept_room_id}}}

Usage:
  uv run python scripts/sync_hav_room_attributes.py            # last 2 days (default)
  uv run python scripts/sync_hav_room_attributes.py --days 7   # last 7 days
  uv run python scripts/sync_hav_room_attributes.py --full     # all-time initial sync
  uv run python scripts/sync_hav_room_attributes.py --dry-run  # preview only
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

BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY_HAV")
BRAZE_BASE_URL = os.environ.get("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com").rstrip("/")
BATCH_SIZE = 75  # Braze /users/track limit per request


def fetch_rooms(days: int | None) -> list[dict]:
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")

    if days is None:
        date_filter = ""
    else:
        date_filter = f"AND CONCEPT_DELIVERED_AT >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())"

    query = f"""
        SELECT
            USER_ID,
            ROOM_ID
        FROM PROD.ANALYTICS.ROOM_DIMS
        WHERE CONCEPT_DELIVERED_AT IS NOT NULL
          AND USER_ID IS NOT NULL
          {date_filter}
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY USER_ID ORDER BY CONCEPT_DELIVERED_AT DESC
        ) = 1
    """
    rows = client.execute_query(query)
    return [{"user_id": str(r["USER_ID"]), "room_id": int(r["ROOM_ID"])} for r in rows]


def push_to_braze(batch: list[dict], dry_run: bool) -> int:
    attributes = [
        {"external_id": r["user_id"], "concept_room_id": r["room_id"]}
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
                        help="Lookback window in days (default: 2). Use --full for all-time.")
    parser.add_argument("--full", action="store_true",
                        help="Full sync — all users with a concept delivery ever.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Braze.")
    args = parser.parse_args()

    if not BRAZE_API_KEY:
        print("ERROR: BRAZE_API_KEY_HAV not set", file=sys.stderr)
        sys.exit(1)

    days = None if args.full else args.days
    label = "all-time" if args.full else f"last {days} days"
    print(f"Fetching HAV rooms with concept delivered ({label})...")

    rooms = fetch_rooms(days)
    print(f"Found {len(rooms)} users to update")

    if not rooms:
        print("Nothing to sync.")
        return

    total = 0
    for i in range(0, len(rooms), BATCH_SIZE):
        batch = rooms[i:i + BATCH_SIZE]
        processed = push_to_braze(batch, args.dry_run)
        total += processed
        print(f"  Batch {i // BATCH_SIZE + 1}: {processed} attributes written")
        if not args.dry_run and i + BATCH_SIZE < len(rooms):
            time.sleep(0.5)  # stay under Braze rate limit

    action = "would update" if args.dry_run else "updated"
    print(f"Done — {action} {total} Braze profiles with concept_room_id")


if __name__ == "__main__":
    main()

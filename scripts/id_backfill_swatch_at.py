#!/usr/bin/env python3
"""
Backfill last_ordered_swatch_at for ID users who ordered swatches before 2026-04-27.

The "Update Last Ordered Swatch At Attribute" canvas launched on 2026-04-27 and sets
last_ordered_swatch_at going forward. This script backfills the attribute for users
whose swatch orders predate the canvas — only updating Braze profiles that already
exist and don't have the attribute set yet.

For the bulk run, braze_id lookups and the already-set check are done efficiently via
the TIER3 Braze datashare (no per-user API calls needed). For single-email tests,
the standard /users/export/ids API is used instead.

Usage:
  # Dry run — see counts without touching Braze
  uv run python scripts/id_backfill_swatch_at.py --dry-run

  # Single user test (uses /users/export/ids API)
  uv run python scripts/id_backfill_swatch_at.py --email user@example.com

  # Staged rollout
  uv run python scripts/id_backfill_swatch_at.py --limit 500

  # Full backfill
  uv run python scripts/id_backfill_swatch_at.py

API key requirement:
  BRAZE_USERS_API_KEY_ID in .env with TWO permissions:
    - User Data: users.export.ids  (used for single-email test only)
    - User Data: users.track       (required for all modes that write to Braze)
  The existing BRAZE_API_KEY_ID is campaign-read-only and will not work.
"""

import os
import sys
import time
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowflake_client import get_snowflake_client

load_dotenv()

BRAZE_URL = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
CUTOFF = "2026-04-27 23:59:59+00:00"
ATTRIBUTE_NAME = "last_ordered_swatch_at"
ID_APP_GROUP = "6666726b459b5e0059d7d687"

TIER3_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
TIER3_SCHEMA = "DATALAKE_SHARING_TIERED"


# ---------------------------------------------------------------------------
# Snowflake queries
# ---------------------------------------------------------------------------

def fetch_swatch_orderers(single_email: str | None = None) -> list[dict]:
    """Most recent swatch order per customer email, on or before CUTOFF."""
    client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")
    email_filter = f"AND LOWER(dc.EMAIL) = '{single_email.lower()}'" if single_email else ""
    rows = client.execute_query(f"""
        SELECT
            LOWER(dc.EMAIL)     AS email,
            MAX(soi.CREATED_AT) AS last_swatch_ordered_at
        FROM PROD.ID_WAREHOUSE.swatch_order_items soi
        JOIN PROD.ID_WAREHOUSE.DIM_CUSTOMERS dc
            ON dc.COBAIN_CUSTOMER_ID = soi.CUSTOMER_ID
        WHERE soi.CREATED_AT <= '{CUTOFF}'
          AND dc.EMAIL IS NOT NULL
          {email_filter}
        GROUP BY LOWER(dc.EMAIL)
    """)
    return [dict(r) for r in rows]


def fetch_email_to_braze_id() -> dict[str, str]:
    """
    Build email → braze_id map from the TIER3 datashare.
    One row per email (most recent profile record wins).
    """
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    rows = client.execute_query(f"""
        SELECT LOWER(EMAIL_ADDRESS) AS email, USER_ID AS braze_id
        FROM {TIER3_DB}.{TIER3_SCHEMA}.USER_DEFAULT_ATTRIBUTES_VIEW_SHARED
        WHERE APP_GROUP_ID = '{ID_APP_GROUP}'
          AND EMAIL_ADDRESS IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY LOWER(EMAIL_ADDRESS) ORDER BY TIME DESC) = 1
    """)
    return {r["EMAIL"]: r["BRAZE_ID"] for r in rows}


def fetch_already_set_braze_ids() -> set[str]:
    """
    Return the set of braze_ids that already have last_ordered_swatch_at set.
    Uses CUSTOM_ATTRIBUTES VARIANT column in the TIER3 datashare.
    """
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    rows = client.execute_query(f"""
        SELECT USER_ID
        FROM {TIER3_DB}.{TIER3_SCHEMA}.USER_CUSTOM_ATTRIBUTES_VIEW_SHARED
        WHERE APP_GROUP_ID = '{ID_APP_GROUP}'
          AND CUSTOM_ATTRIBUTES:{ATTRIBUTE_NAME} IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY TIME DESC) = 1
    """)
    return {r["USER_ID"] for r in rows}


# ---------------------------------------------------------------------------
# Single-email test path (uses /users/export/ids API)
# ---------------------------------------------------------------------------

def lookup_single_user(email: str, api_key: str) -> tuple[str | None, bool]:
    """
    Returns (braze_id, attribute_already_set).
    Returns (None, False) if the user doesn't exist in Braze.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{BRAZE_URL}/users/export/ids"

    resp = requests.post(url, json={"email_address": email}, headers=headers, timeout=15)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        print(f"  Rate limited — sleeping {retry_after}s")
        time.sleep(retry_after)
        resp = requests.post(url, json={"email_address": email}, headers=headers, timeout=15)

    if resp.status_code not in (200, 201):
        print(f"  Warning: export/ids returned {resp.status_code} for {email[:5]}***")
        return None, False

    users = resp.json().get("users", [])
    if not users:
        return None, False

    user = users[0]
    braze_id = user.get("braze_id")
    already_set = bool(user.get("custom_attributes", {}).get(ATTRIBUTE_NAME))
    return braze_id, already_set


# ---------------------------------------------------------------------------
# Braze write
# ---------------------------------------------------------------------------

def push_braze_attributes(records: list[dict], api_key: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{BRAZE_URL}/users/track"
    batch_size = 75
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        resp = requests.post(url, json={"attributes": batch}, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", [])
        if errors:
            print(f"  Batch {i // batch_size + 1}: {len(batch)} users — {len(errors)} errors: {errors[:2]}")
        else:
            print(f"  Batch {i // batch_size + 1}: {len(batch)} users pushed OK")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill last_ordered_swatch_at for ID swatch orderers pre-4/27/2026"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Query all data sources, print counts, skip Braze write")
    parser.add_argument("--email",
                        help="Process only this single email (uses /users/export/ids API)")
    parser.add_argument("--limit", type=int,
                        help="Cap at N users for staged rollout")
    parser.add_argument("--skip-check", action="store_true",
                        help="Skip the already-set check — write for all matched users")
    args = parser.parse_args()

    api_key = os.environ.get("BRAZE_USERS_API_KEY_ID")
    if not api_key and not args.dry_run:
        print("ERROR: BRAZE_USERS_API_KEY_ID not set.")
        print("  Create an API key in the ID Braze workspace with:")
        print("    - User Data: users.export.ids")
        print("    - User Data: users.track")
        print("  Then add BRAZE_USERS_API_KEY_ID=<key> to .env")
        sys.exit(1)

    # ------------------------------------------------------------------
    # SINGLE-EMAIL TEST PATH
    # ------------------------------------------------------------------
    if args.email:
        print(f"Single-email test for {args.email[:5]}***\n")

        print("Querying swatch orders from Snowflake...")
        rows = fetch_swatch_orderers(single_email=args.email)
        if not rows:
            print("  No swatch order found for this email before the cutoff.")
            return
        ts = rows[0]["LAST_SWATCH_ORDERED_AT"]
        print(f"  Last swatch order: {ts}")

        if args.dry_run:
            print("\n[dry-run] Would look up braze_id and set attribute. Skipping.")
            return

        print("\nLooking up user in Braze...")
        braze_id, already_set = lookup_single_user(args.email, api_key)
        if braze_id is None:
            print("  User not found in Braze — skipping.")
            return
        print(f"  braze_id: {braze_id}")
        print(f"  {ATTRIBUTE_NAME} already set: {already_set}")

        if already_set and not args.skip_check:
            print("  Attribute already set — nothing to do. Use --skip-check to overwrite.")
            return

        print(f"\nPushing {ATTRIBUTE_NAME} = {ts}...")
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        push_braze_attributes([{"braze_id": braze_id, ATTRIBUTE_NAME: ts_str}], api_key)
        print("Done. Verify in Braze UI → User Search → check custom attributes.")
        return

    # ------------------------------------------------------------------
    # BULK PATH — uses TIER3 datashare for efficient lookups
    # ------------------------------------------------------------------
    print("Step 1/3: Querying swatch orders from Snowflake...")
    customers = fetch_swatch_orderers()
    print(f"  {len(customers)} unique customer emails with swatch orders ≤ cutoff")

    print("\nStep 2/3: Loading braze_id map from TIER3 datashare...")
    email_to_braze_id = fetch_email_to_braze_id()
    print(f"  {len(email_to_braze_id)} ID users with email addresses in Braze")

    already_set: set[str] = set()
    if not args.skip_check:
        print(f"\n  Checking which users already have {ATTRIBUTE_NAME} set...")
        already_set = fetch_already_set_braze_ids()
        print(f"  {len(already_set)} users already have the attribute set")

    print("\nStep 3/3: Building update list...")
    to_update: list[dict] = []
    skipped_not_in_braze = 0
    skipped_already_set = 0

    for row in customers:
        email = row["EMAIL"]
        ts = row["LAST_SWATCH_ORDERED_AT"]
        braze_id = email_to_braze_id.get(email)

        if braze_id is None:
            skipped_not_in_braze += 1
            continue
        if braze_id in already_set and not args.skip_check:
            skipped_already_set += 1
            continue

        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        to_update.append({"braze_id": braze_id, ATTRIBUTE_NAME: ts_str})

    if args.limit:
        to_update = to_update[:args.limit]
        print(f"  Capped at {args.limit} users (--limit)")

    print(f"\n  To update:       {len(to_update)}")
    print(f"  Not in Braze:    {skipped_not_in_braze}")
    print(f"  Already set:     {skipped_already_set}")

    if args.dry_run:
        print("\n[dry-run] Skipping Braze write.")
        if to_update:
            print("  Sample (first 3):")
            for r in to_update[:3]:
                print(f"    {r['braze_id'][:8]}... → {r[ATTRIBUTE_NAME]}")
        return

    if not to_update:
        print("Nothing to push.")
        return

    print(f"\nPushing {ATTRIBUTE_NAME} for {len(to_update)} users in batches of 75...")
    push_braze_attributes(to_update, api_key)
    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Daily sync: push pre-arrival delivery attributes to Braze for ID customers.

Queries PROD.ID_WAREHOUSE for furniture orders with QUOTED_MIN_DELIVERY_DATE
in the 21-28 day window, filters out customers who have already purchased from
a partner brand (CZ, BUR, STF, HAV, TI), then pushes two Braze attributes:
  - id_est_delivery_date:  ISO date string (earliest quoted delivery)
  - id_purchase_category:  "bed" or "sofa_sectional"

Because ID has no consistent external_id format in Braze, users are identified
via a two-step lookup:
  1. /users/export/ids?email_address=X  → returns braze_id
  2. /users/track with braze_id         → updates attributes in place

Users not found by email (not in Braze) are skipped — no new profiles created.
Users found are updated in place — no duplicate profiles possible.

Canvases this enables:
  TRG_EM_*_ID_D_Complete_Your_Bedroom_CZ    (bed buyers)
  TRG_EM_*_ID_D_Finish_Your_Living_Room     (sofa/sectional buyers)

Canvas entry filters:
  id_purchase_category = "bed" | "sofa_sectional"
  id_est_delivery_date is within the next 28 days

Usage:
  uv run python scripts/id_pre_arrival_sync.py [--dry-run] [--days-min N] [--days-max N]

API key requirement:
  BRAZE_USERS_API_KEY_ID in the ID workspace with TWO permissions:
    - User Data: users.export.ids  (email → braze_id lookup)
    - User Data: users.track       (attribute push)
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
from id_cross_brand_suppression import get_all_cross_brand_purchasers

load_dotenv()

BRAZE_URL = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
MERCH_CLASS_TO_CATEGORY = {
    "Beds": "bed",
    "Sofas": "sofa_sectional",
    "Sectionals": "sofa_sectional",
}
EXCLUDED_STATUSES = ("'delivered'", "'cancellation'", "'closed'")


def fetch_pre_arrival_customers(days_min: int = 21, days_max: int = 28) -> list[dict]:
    client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")
    rows = client.execute_query(f"""
        SELECT DISTINCT
            dc.EMAIL                              AS email,
            ois.QUOTED_MIN_DELIVERY_DATE          AS est_delivery_date,
            dp.MERCH_CLASS                        AS merch_class
        FROM PROD.ID_WAREHOUSE.STG_ORDER_ITEM_STATUSES ois
        JOIN PROD.ID_WAREHOUSE.ORDERS o
            ON o.COBAIN_SALES_ORDER_ID = ois.COBAIN_SALES_ORDER_ID
        JOIN PROD.ID_WAREHOUSE.DIM_CUSTOMERS dc
            ON dc.COBAIN_CUSTOMER_ID = o.CUSTOMER_ID
        JOIN PROD.ID_WAREHOUSE.DIM_PRODUCTS dp
            ON dp.SKU = ois.PRODUCT_SKU
        WHERE dp.MERCH_CLASS IN ('Beds', 'Sofas', 'Sectionals')
          AND ois.QUOTED_MIN_DELIVERY_DATE
                BETWEEN DATEADD('day', {days_min}, CURRENT_DATE())
                    AND DATEADD('day', {days_max}, CURRENT_DATE())
          AND ois.OI_STATUS NOT IN ({', '.join(EXCLUDED_STATUSES)})
          AND dc.EMAIL IS NOT NULL
    """)
    return [dict(r) for r in rows]


def lookup_braze_ids(emails: list[str], api_key: str) -> dict[str, str]:
    """
    Look up braze_id for each email via /users/export/ids.

    Returns a dict of {email: braze_id} for emails found in Braze.
    Emails not found (user doesn't exist) are omitted from the result.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{BRAZE_URL}/users/export/ids"
    result: dict[str, str] = {}

    for i, email in enumerate(emails):
        resp = requests.post(url, json={"email_address": email}, headers=headers, timeout=15)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"  Rate limited — sleeping {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(url, json={"email_address": email}, headers=headers, timeout=15)

        if resp.status_code != 200:
            print(f"  Warning: export/ids returned {resp.status_code} for {email[:5]}***")
            continue

        users = resp.json().get("users", [])
        if users:
            result[email] = users[0]["braze_id"]

        # Stay well under the rate limit (250 req/min for this endpoint)
        if (i + 1) % 50 == 0:
            print(f"  Looked up {i + 1}/{len(emails)} emails ({len(result)} found so far)...")
        time.sleep(0.25)

    return result


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


def main():
    parser = argparse.ArgumentParser(description="Push pre-arrival delivery attributes to Braze for ID customers")
    parser.add_argument("--dry-run", action="store_true", help="Query data but skip Braze push")
    parser.add_argument("--days-min", type=int, default=21)
    parser.add_argument("--days-max", type=int, default=28)
    args = parser.parse_args()

    api_key = os.environ.get("BRAZE_USERS_API_KEY_ID")
    if not api_key and not args.dry_run:
        print("ERROR: BRAZE_USERS_API_KEY_ID not set.")
        print("  Create a Braze API key in the ID workspace with:")
        print("    - User Data: users.export.ids")
        print("    - User Data: users.track")
        print("  Then add BRAZE_USERS_API_KEY_ID=<key> to .env")
        sys.exit(1)

    # Step 1: Build cross-brand suppression set
    print("Building cross-brand purchaser set...")
    cross_brand = get_all_cross_brand_purchasers()

    # Step 2: Fetch delivery-window customers
    print(f"\nFetching ID customers with delivery in {args.days_min}-{args.days_max} days...")
    customers = fetch_pre_arrival_customers(days_min=args.days_min, days_max=args.days_max)
    print(f"Found {len(customers)} order line items")

    # Step 3: Filter cross-brand purchasers
    filtered = [r for r in customers if r["EMAIL"].lower() not in cross_brand]
    suppressed = len(customers) - len(filtered)
    print(f"  Suppressed {suppressed} cross-brand purchasers → {len(filtered)} remaining")

    beds = sum(1 for r in filtered if r["MERCH_CLASS"] == "Beds")
    sofas = len(filtered) - beds
    print(f"  Beds: {beds}, Sofas/Sectionals: {sofas}")

    if args.dry_run:
        print("\n[dry-run] Skipping braze_id lookup and push.")
        print("  Sample qualifying customers:")
        for r in filtered[:3]:
            print(f"    {r['EMAIL'][:5]}*** — {r['MERCH_CLASS']} — delivery {r['EST_DELIVERY_DATE']}")
        return

    # Step 4: Look up braze_id for each qualifying email
    emails = [r["EMAIL"].lower() for r in filtered]
    print(f"\nLooking up braze_id for {len(emails)} emails...")
    email_to_braze_id = lookup_braze_ids(emails, api_key)
    found = len(email_to_braze_id)
    skipped = len(emails) - found
    print(f"  Found: {found}, Not in Braze (skipped): {skipped}")

    if not email_to_braze_id:
        print("No users found in Braze. Nothing to push.")
        return

    # Step 5: Build attribute objects using braze_id (no external_id involved)
    attributes = []
    for row in filtered:
        braze_id = email_to_braze_id.get(row["EMAIL"].lower())
        if braze_id:
            attributes.append({
                "braze_id": braze_id,
                "id_est_delivery_date": f"{row['EST_DELIVERY_DATE'].isoformat()}T00:00:00Z",
                "id_purchase_category": MERCH_CLASS_TO_CATEGORY[row["MERCH_CLASS"]],
            })

    # Step 6: Push attributes
    print(f"\nPushing attributes for {len(attributes)} users...")
    push_braze_attributes(attributes, api_key)
    print("Done.")


if __name__ == "__main__":
    main()

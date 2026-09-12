#!/usr/bin/env python3
"""
Sync the `board_product_recommendations` Braze attribute for HAV.

Snowflake-sourced sibling of the engineering-owned `on_sale_product_recommendations`
attribute: same item structure, but includes BOTH on-sale and full-price products
from the user's design board. Built for the lifecycle rebuild's Stage 5
("Ready to Shop") — "here's everything your designer picked".

Source of items: the user's most recently published designer board
(FIVETRAN_DB.REPLICA_HAVENLY_APP.BOARDS joined to PROD.ANALYTICS.DESIGNER_ROOM_BOARDS),
"definite" non-substitute board products only, joined to PROD.ANALYTICS.PRODUCT_CATALOG
for live title/vendor/price/sale_price/image, in-stock items only. Ranked by price
desc, capped at MAX_ITEMS per user.

Never creates new Braze profiles — two guards:
  1. SQL INNER JOIN against the Braze datashare current-state profile view
     (USER_DEFAULT_ATTRIBUTES_VIEW_SHARED, non-archived) so only external_ids
     that exist in Braze right now are selected.
  2. `_update_existing_only: true` on every /users/track attributes object.

Usage:
  uv run python scripts/sync_board_product_recommendations.py --dry-run --limit 5
  uv run python scripts/sync_board_product_recommendations.py --user-id 3576474
  uv run python scripts/sync_board_product_recommendations.py            # full sync

Adapted from scripts/sync_hav_hip_audience.py.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.snowflake_client import get_snowflake_client

BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY_HAV_USERS") or os.environ.get("BRAZE_API_KEY_HAV")
BRAZE_BASE_URL = os.environ.get("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com").rstrip("/")
BATCH_SIZE = 75  # Braze /users/track limit per request
MAX_WORKERS = 8  # concurrent /users/track requests (limit is 3,000 req / 3s)
HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"
BRAZE_DATASHARE_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
ATTRIBUTE_NAME = "board_product_recommendations"
MAX_ITEMS = 20  # Braze array-of-objects limit is 50; existing attribute runs 8-17

# PRODUCT_CATALOG.DIVISION -> group_category labels used by on_sale_product_recommendations
DIVISION_TO_GROUP_CATEGORY = {
    "furniture": "Main Items",
    "rugs": "Rugs",
    "lighting": "Lighting",
    "decor": "Decor",
    "hard goods": "Hard Goods",
}


def _fmt_price(value) -> str:
    """Match the existing attribute's price format: '1,899.00' / '15.30'."""
    return f"{float(value):,.2f}"


def _group_category(division, category) -> str:
    for source in (division, category):
        if source:
            label = DIVISION_TO_GROUP_CATEGORY.get(str(source).strip().lower())
            if label:
                return label
    return "Other"


def _build_query(user_id: str | None = None) -> str:
    """Build the per-user recommendations SQL. One row per user: external_id +
    JSON array of board product items."""
    user_filter = ""
    if user_id:
        user_filter = f"AND b.USER_ID = {int(user_id)}"
    return f"""
        WITH braze_exists AS (
            -- current-state profile view: unlike the email-send event log, this
            -- excludes deleted/archived profiles and includes never-emailed ones
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM {BRAZE_DATASHARE_DB}.DATALAKE_SHARING.USER_DEFAULT_ATTRIBUTES_VIEW_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IS NOT NULL
              AND (ARCHIVED IS NULL OR ARCHIVED = FALSE)
        ),
        designer_boards AS (
            SELECT DISTINCT BOARD_ID FROM PROD.ANALYTICS.DESIGNER_ROOM_BOARDS
        ),
        latest_board AS (
            SELECT
                b.USER_ID,
                b.ID AS BOARD_ID,
                b.ROOM_ID,
                ROW_NUMBER() OVER (PARTITION BY b.USER_ID ORDER BY b.PUBLISHED DESC, b.ID DESC) AS rn
            FROM FIVETRAN_DB.REPLICA_HAVENLY_APP.BOARDS b
            JOIN designer_boards db ON db.BOARD_ID = b.ID
            JOIN braze_exists be ON be.EXTERNAL_USER_ID = b.USER_ID::STRING
            WHERE b.PUBLISHED IS NOT NULL
              AND b.DELETED IS NULL
              AND b._FIVETRAN_DELETED = FALSE
              AND b.USER_ID IS NOT NULL
              {user_filter}
        ),
        board_items AS (
            SELECT
                lb.USER_ID,
                lb.ROOM_ID,
                -- display label to match on_sale_product_recommendations (e.g. "Design Complete")
                COALESCE(rs.TITLE, r.ROOM_STATUS) AS ROOM_STATUS,
                r.ROOM_STATUS_ID,
                pc.VENDOR_VARIANT_ID,
                pc.PRODUCT_TITLE,
                pc.VENDOR_NAME,
                pc.PRICE,
                pc.SALE_PRICE,
                pc.IMAGE_URL,
                pc.DIVISION,
                pc.CATEGORY,
                ROW_NUMBER() OVER (
                    PARTITION BY lb.USER_ID, pc.VENDOR_VARIANT_ID ORDER BY pc.PRICE DESC
                ) AS dedupe_rn
            FROM latest_board lb
            JOIN FIVETRAN_DB.REPLICA_HAVENLY_APP.BOARD_PRODUCTS bp
                ON bp.BOARD_ID = lb.BOARD_ID
               AND bp._FIVETRAN_DELETED = FALSE
               AND bp.BOARD_PRODUCT_STATUS_ID = 2   -- definite (placed in design)
               AND bp.SUB_FOR IS NULL               -- exclude substitutes/alternates
            JOIN PROD.ANALYTICS.PRODUCT_CATALOG pc
                ON pc.VENDOR_VARIANT_ID = bp.VENDOR_VARIANT_ID
            JOIN PROD.ANALYTICS.ROOMS_CLEAN r
                ON r.ROOM_ID = lb.ROOM_ID
            LEFT JOIN FIVETRAN_DB.REPLICA_HAVENLY_APP.ROOM_STATUSES rs
                ON rs.ID = r.ROOM_STATUS_ID AND rs._FIVETRAN_DELETED = FALSE
            WHERE lb.rn = 1
              AND pc.AVAILABILITY = 'In-Stock'
              AND pc.PRICE IS NOT NULL AND pc.PRICE > 0
              AND (r.IS_REFUNDED IS NULL OR r.IS_REFUNDED = 0)
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY PRICE DESC, VENDOR_VARIANT_ID) AS ITEM_RANK
            FROM board_items
            WHERE dedupe_rn = 1
        )
        SELECT
            USER_ID::STRING AS USER_ID,
            ARRAY_AGG(OBJECT_CONSTRUCT(
                'vendor_variant_id', VENDOR_VARIANT_ID,
                'product_title', PRODUCT_TITLE,
                'vendor_name', VENDOR_NAME,
                'price', PRICE,
                'sale_price', COALESCE(SALE_PRICE, PRICE),
                'image_url', IMAGE_URL,
                'division', DIVISION,
                'category', CATEGORY,
                'rank', ITEM_RANK,
                'room_id', ROOM_ID,
                'room_status', ROOM_STATUS,
                'room_status_id', ROOM_STATUS_ID
            )) WITHIN GROUP (ORDER BY ITEM_RANK) AS ITEMS
        FROM ranked
        WHERE ITEM_RANK <= {MAX_ITEMS}
        GROUP BY 1
    """


def fetch_recommendations(user_id: str | None = None) -> list[dict]:
    """Materialize all recommendation rows (used for single-user / test paths)."""
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")
    return client.execute_query(_build_query(user_id))


def stream_recommendations(user_id: str | None = None, chunk_size: int = 5000):
    """Yield recommendation rows in chunks so we never hold all ~109K users
    (each with a ~20-item nested array) in memory at once."""
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")
    yield from client.execute_query_iter(_build_query(user_id), chunk_size=chunk_size)


def build_payload_items(raw_items: list[dict], synced_at_iso: str) -> list[dict]:
    """Convert raw SQL items into the on_sale_product_recommendations item schema."""
    out = []
    for item in raw_items:
        out.append({
            "group_category": _group_category(item.get("division"), item.get("category")),
            "last_updated_at": synced_at_iso,
            "multiplier": 0,  # structural parity only; commission weighting not replicated
            "price": _fmt_price(item["price"]),
            "product_image_url": item.get("image_url"),
            "product_link": f"https://havenly.com/products/details/{item['vendor_variant_id']}",
            "product_title": item.get("product_title"),
            "rank": item["rank"],
            "room_id": item["room_id"],
            "room_status": item.get("room_status"),
            "room_status_id": item.get("room_status_id"),
            "sale_price": _fmt_price(item["sale_price"]),
            "vendor_name": item.get("vendor_name"),
        })
    return out


def push_to_braze(attributes: list[dict], dry_run: bool) -> int:
    if dry_run:
        for attr in attributes[:2]:
            print(f"  [dry-run] {json.dumps(attr, indent=2)[:2500]}")
        if len(attributes) > 2:
            print(f"  [dry-run] ... and {len(attributes) - 2} more users in this batch")
        return len(attributes)

    resp = requests.post(
        f"{BRAZE_BASE_URL}/users/track",
        headers={
            "Authorization": f"Bearer {BRAZE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"attributes": attributes},
        timeout=60,
    )
    if resp.status_code == 429:
        print("  Rate limited — waiting 60s")
        time.sleep(60)
        return push_to_braze(attributes, dry_run)
    resp.raise_for_status()
    result = resp.json()
    errors = result.get("errors", [])
    if errors:
        print(f"  Braze errors: {errors}")
    return result.get("attributes_processed", len(attributes))


def _send_in_batches(attributes: list[dict], dry_run: bool) -> int:
    batches = [attributes[i:i + BATCH_SIZE] for i in range(0, len(attributes), BATCH_SIZE)]
    total = 0
    if dry_run:
        for batch in batches:
            total += push_to_braze(batch, dry_run)
        return total

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(push_to_braze, batch, dry_run) for batch in batches]
        for future in as_completed(futures):
            total += future.result()
            done += 1
            if done % 50 == 0 or done == len(batches):
                print(f"  batch {done}/{len(batches)}: {total} attributes processed so far",
                      flush=True)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Braze.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only sync the first N users (testing).")
    parser.add_argument("--user-id", default=None,
                        help="Only sync a single Havenly user id (testing).")
    args = parser.parse_args()

    if not BRAZE_API_KEY and not args.dry_run:
        print("ERROR: BRAZE_API_KEY_HAV_USERS (or BRAZE_API_KEY_HAV) not set", file=sys.stderr)
        sys.exit(1)

    synced_at_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")
    print(f"Streaming board product recommendations from Snowflake"
          f"{' for user ' + args.user_id if args.user_id else ''}...", flush=True)

    # Stream + push in chunks so we never hold all ~109K users (each with a
    # ~20-item nested array) in memory at once — materializing everything peaks
    # at ~3GB and OOM-thrashes the CI runner.
    total_users = 0
    total_items = 0
    total_written = 0
    stopped = False
    for row_chunk in stream_recommendations(user_id=args.user_id):
        attributes = []
        for row in row_chunk:
            if args.limit and total_users >= args.limit:
                stopped = True
                break
            raw_items = json.loads(row["ITEMS"]) if isinstance(row["ITEMS"], str) else row["ITEMS"]
            items = build_payload_items(raw_items, synced_at_iso)
            if not items:
                continue
            total_users += 1
            total_items += len(items)
            attributes.append({
                "external_id": row["USER_ID"],
                "_update_existing_only": True,  # never create a new Braze profile
                ATTRIBUTE_NAME: items,
            })
        if attributes:
            total_written += _send_in_batches(attributes, args.dry_run)
            print(f"  progress: {total_users} users pushed ({total_items} items)", flush=True)
        if stopped:
            break

    if total_users == 0:
        print("Nothing to sync.")
        return

    action = "would update" if args.dry_run else "updated"
    print(f"Done — {action} {total_written} profiles "
          f"({total_users} users, {total_items} items, "
          f"avg {total_items / total_users:.1f}/user)")


if __name__ == "__main__":
    main()

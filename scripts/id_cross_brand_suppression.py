#!/usr/bin/env python3
"""
Cross-brand purchase suppression for ID pre-arrival canvases.

Builds a set of emails belonging to customers who have purchased from
at least one partner brand (CZ, BUR, STF, HAV, TI). Used by
id_pre_arrival_sync.py to filter the delivery-window list before pushing
attributes to Braze.

Sources:
  CZ  — FIVETRAN_DB.LANDING_CZ_SHOPIFY.CUSTOMER (ORDERS_COUNT > 0)
  BUR — FIVETRAN_DB.LANDING_BURROW_SHOPIFY.CUSTOMER (ORDERS_COUNT > 0)
  STF — FIVETRAN_DB.LANDING_STF_SHOPIFY.CUSTOMER (ORDERS_COUNT > 0)
  HAV — PROD.ID_WAREHOUSE.ORDERS.HAVENLY_ORDER_DATE IS NOT NULL
  TI  — Klaviyo profiles with historic spend > 0 (KLAVIYO_API_KEY_TI)

Usage (standalone audit mode):
  uv run python scripts/id_cross_brand_suppression.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowflake_client import get_snowflake_client


def get_shopify_purchaser_emails(schema: str, database: str = "FIVETRAN_DB") -> set[str]:
    client = get_snowflake_client(schema=schema, database=database)
    rows = client.execute_query(f"""
        SELECT EMAIL
        FROM {database}.{schema}.CUSTOMER
        WHERE ORDERS_COUNT > 0 AND EMAIL IS NOT NULL
    """)
    return {str(r["EMAIL"]).lower() for r in rows if r["EMAIL"]}


def get_hav_purchaser_emails() -> set[str]:
    """ID customers with a linked Havenly order in ORDERS.HAVENLY_ORDER_DATE."""
    client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")
    rows = client.execute_query("""
        SELECT dc.EMAIL
        FROM PROD.ID_WAREHOUSE.ORDERS o
        JOIN PROD.ID_WAREHOUSE.DIM_CUSTOMERS dc
            ON dc.COBAIN_CUSTOMER_ID = o.CUSTOMER_ID
        WHERE o.HAVENLY_ORDER_DATE IS NOT NULL
          AND dc.EMAIL IS NOT NULL
    """)
    return {str(r["EMAIL"]).lower() for r in rows if r["EMAIL"]}


def get_ti_purchaser_emails() -> set[str]:
    """
    TI customers who have placed at least one order, from Klaviyo.

    Paginates all "Placed Order" events in the TI Klaviyo account, extracts
    profile emails from the included profile data on each page.
    """
    import time
    import requests as _requests

    api_key = os.environ.get("KLAVIYO_API_KEY_TI")
    if not api_key:
        print("  TI: KLAVIYO_API_KEY_TI not set, skipping")
        return set()

    try:
        from utils.klaviyo_client import KlaviyoClient, KLAVIYO_BASE_URL
        client = KlaviyoClient(api_key, brand="TI")

        metric_ids = client.discover_metric_ids()
        placed_order_id = metric_ids.get("Placed Order")
        if not placed_order_id:
            print("  TI: 'Placed Order' metric not found, skipping")
            return set()

        emails: set[str] = set()
        url: str | None = f"{KLAVIYO_BASE_URL}/events/"
        params: dict = {
            "filter": f'equals(metric_id,"{placed_order_id}")',
            "include": "profile",
            "fields[profile]": "email",
        }
        page_count = 0

        while url:
            client._rate_limiter.acquire()
            resp = _requests.get(url, headers=client._headers(), params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                print(f"  TI: events API returned {resp.status_code}, stopping pagination")
                break

            data = resp.json()
            for item in data.get("included", []):
                if item.get("type") == "profile":
                    email = item.get("attributes", {}).get("email")
                    if email:
                        emails.add(email.lower())

            url = data.get("links", {}).get("next")
            params = {}  # cursor URL is self-contained; don't re-send params
            page_count += 1
            if page_count % 20 == 0:
                print(f"  TI: {page_count} pages, {len(emails):,} unique purchasers so far...")

        print(f"  TI: {page_count} pages total, {len(emails):,} unique purchasers")
        return emails

    except Exception as e:
        print(f"  TI: Klaviyo lookup failed ({e}), skipping")
        return set()


def get_all_cross_brand_purchasers() -> set[str]:
    """Return a set of lowercase emails that have purchased from any partner brand."""
    from dotenv import load_dotenv
    load_dotenv()

    print("  CZ (Shopify)...")
    cz = get_shopify_purchaser_emails("LANDING_CZ_SHOPIFY")
    print(f"    {len(cz):,} CZ customers with orders")

    print("  BUR (Shopify)...")
    bur = get_shopify_purchaser_emails("LANDING_BURROW_SHOPIFY")
    print(f"    {len(bur):,} BUR customers with orders")

    print("  STF (Shopify)...")
    stf = get_shopify_purchaser_emails("LANDING_STF_SHOPIFY")
    print(f"    {len(stf):,} STF customers with orders")

    print("  HAV (ID warehouse ORDERS.HAVENLY_ORDER_DATE)...")
    hav = get_hav_purchaser_emails()
    print(f"    {len(hav):,} HAV customers linked to ID orders")

    print("  TI (Klaviyo)...")
    ti = get_ti_purchaser_emails()
    print(f"    {len(ti):,} TI customers with historic spend")

    combined = cz | bur | stf | hav | ti
    print(f"  Total unique cross-brand purchasers: {len(combined):,}")
    return combined


if __name__ == "__main__":
    print("Building cross-brand purchaser set (audit mode)...")
    cross_brand = get_all_cross_brand_purchasers()

    client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")
    rows = client.execute_query("SELECT EMAIL FROM PROD.ID_WAREHOUSE.DIM_CUSTOMERS WHERE EMAIL IS NOT NULL")
    id_emails = {str(r["EMAIL"]).lower() for r in rows if r["EMAIL"]}

    overlap = id_emails & cross_brand
    print(f"\nID customers: {len(id_emails):,}")
    print(f"Cross-brand purchasers: {len(cross_brand):,}")
    print(f"ID customers who will be suppressed: {len(overlap):,} ({len(overlap)/len(id_emails)*100:.1f}%)")

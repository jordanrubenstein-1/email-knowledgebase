#!/usr/bin/env python
"""Backfill `has_purchased = true` on existing TI (The Inside) Klaviyo profiles.

Purpose
-------
An email block is shown only when a profile has NOT placed an order (property
`has_purchased` is not set). A flow sets `has_purchased = true` going forward when
the custom `OrderPlaced` metric fires. This script backfills that flag for people who
already purchased BEFORE the flow existed.

Safety
------
Profiles are updated with PATCH /profiles/{id}/ using the profile ID only. PATCH-by-ID
updates an existing profile or 404s — it NEVER creates a new profile. Every ID comes
from a Klaviyo segment of existing profiles, so no new profiles can be created.

Definition of "purchaser"
-------------------------
Matches the flow trigger exactly: custom metric `OrderPlaced` (id Krer26), count > 0,
all time. (NOT the Shopify "Placed Order" metric HdcfkG.)

Usage
-----
    uv run python scripts/backfill_ti_has_purchased.py --dry-run      # count only, no writes
    uv run python scripts/backfill_ti_has_purchased.py --execute --limit 5   # test on 5 profiles
    uv run python scripts/backfill_ti_has_purchased.py --execute      # full backfill
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from utils.klaviyo_client import KLAVIYO_BASE_URL, KlaviyoClient  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

# --- TI-specific constants (verified via MCP on 2026-07-02) --------------------
ORDERPLACED_METRIC_ID = "Krer26"          # custom API "OrderPlaced" metric
PROPERTY_NAME = "has_purchased"
PROPERTY_VALUE = True
SEGMENT_NAME = "has_purchased backfill — OrderPlaced > 0 all time"


def init_client() -> KlaviyoClient:
    api_key = os.environ.get("KLAVIYO_API_KEY_TI")
    if not api_key:
        print("Error: KLAVIYO_API_KEY_TI not set in .env")
        sys.exit(1)
    return KlaviyoClient(api_key=api_key, brand="TI")


def find_or_create_segment(client: KlaviyoClient) -> str:
    """Return the ID of the OrderPlaced>0 segment, creating it if absent."""
    existing = client.find_list_or_segment_by_name(SEGMENT_NAME)
    if existing:
        print(f"  Reusing existing segment: {existing}")
        return existing

    body = {
        "data": {
            "type": "segment",
            "attributes": {
                "name": SEGMENT_NAME,
                "definition": {
                    "condition_groups": [
                        {
                            "conditions": [
                                {
                                    "type": "profile-metric",
                                    "metric_id": ORDERPLACED_METRIC_ID,
                                    "measurement": "count",
                                    "measurement_filter": {
                                        "type": "numeric",
                                        "operator": "greater-than",
                                        "value": 0,
                                    },
                                    "timeframe_filter": {
                                        "type": "date",
                                        "operator": "alltime",
                                    },
                                    "metric_filters": None,
                                }
                            ]
                        }
                    ]
                },
            },
        }
    }
    result = client._post("/segments/", body)
    if not result:
        print("Error: failed to create segment")
        sys.exit(1)
    seg_id = result["data"]["id"]
    print(f"  Created segment: {seg_id}")
    return seg_id


def wait_for_segment(client: KlaviyoClient, seg_id: str, timeout_s: int = 1800) -> int:
    """Poll until the segment finishes processing. Returns profile_count."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client._get(
            f"/segments/{seg_id}/",
            params={"additional-fields[segment]": "profile_count"},
        )
        attrs = (data or {}).get("data", {}).get("attributes", {})
        processing = attrs.get("is_processing")
        count = attrs.get("profile_count")
        print(f"    processing={processing} profile_count={count}")
        if processing is False:
            return count or 0
        time.sleep(15)
    print("Warning: segment still processing after timeout; proceeding with current members")
    return -1


def collect_profile_ids(client: KlaviyoClient, seg_id: str) -> list[str]:
    """Page all profile IDs in the segment."""
    ids: list[str] = []
    params = {"fields[profile]": "email", "page[size]": 100}
    next_url: str | None = f"/segments/{seg_id}/profiles/"
    is_first = True
    while next_url:
        data = client._get(next_url, params=params) if is_first else client._get(next_url)
        is_first = False
        if not data:
            break
        for prof in data.get("data", []):
            ids.append(prof["id"])
        next_url = (data.get("links") or {}).get("next")
        print(f"    collected {len(ids)} profile IDs...")
    return ids


def patch_profile(client: KlaviyoClient, profile_id: str, retries: int = 5) -> bool:
    """PATCH a single profile's has_purchased property. Update-by-ID only (never creates)."""
    url = f"{KLAVIYO_BASE_URL}/profiles/{profile_id}/"
    payload = {
        "data": {
            "type": "profile",
            "id": profile_id,
            "attributes": {"properties": {PROPERTY_NAME: PROPERTY_VALUE}},
        }
    }
    client._rate_limiter.acquire()
    for attempt in range(retries):
        try:
            resp = requests.patch(url, headers=client._headers(), json=payload, timeout=30)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in (200, 204):
                return True
            print(f"  [patch] {profile_id}: {resp.status_code} {resp.text[:200]}")
            return False
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"  [patch] {profile_id} failed: {e}")
                return False
            time.sleep(2 ** attempt)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Count target profiles, no writes")
    g.add_argument("--execute", action="store_true", help="Perform the backfill")
    ap.add_argument("--limit", type=int, default=None, help="Cap number of profiles patched (testing)")
    args = ap.parse_args()

    client = init_client()

    print(f"[1/4] Finding/creating segment '{SEGMENT_NAME}'...")
    seg_id = find_or_create_segment(client)

    print("[2/4] Waiting for segment to finish processing...")
    count = wait_for_segment(client, seg_id)

    print("[3/4] Collecting existing profile IDs...")
    ids = collect_profile_ids(client, seg_id)
    print(f"  Total existing profiles with OrderPlaced > 0: {len(ids)}")

    if args.dry_run:
        print("\n[DRY RUN] No profiles modified.")
        print(f"  Would set {PROPERTY_NAME}={PROPERTY_VALUE} on {len(ids)} profiles.")
        print(f"  Segment ID (kept): {seg_id}")
        return

    targets = ids[: args.limit] if args.limit else ids
    print(f"[4/4] Patching {len(targets)} profiles (of {len(ids)})...")
    ok = fail = 0
    for i, pid in enumerate(targets, 1):
        if patch_profile(client, pid):
            ok += 1
            if len(targets) <= 20:
                print(f"    patched {pid}")
        else:
            fail += 1
        if i % 100 == 0 or i == len(targets):
            print(f"    {i}/{len(targets)}  ok={ok} fail={fail}")

    print(f"\nDone. Updated {ok} profiles, {fail} failed. Segment ID: {seg_id}")
    if fail == 0 and not args.limit:
        print("You can delete the temporary segment in Klaviyo if you don't need it.")


if __name__ == "__main__":
    main()

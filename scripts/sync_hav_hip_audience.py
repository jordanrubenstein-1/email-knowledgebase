#!/usr/bin/env python3
"""
Sync the Havenly In-Person (HIP) geo-targeted audience to Braze.

Flags a specific cohort of EXISTING HAV Braze profiles and sets two custom
attributes via /users/track:
  - hip_eligible : True  (segment on this for the HIP email)
  - hip_market   : "Austin" / "Boston" / ... (city label for {{custom_attribute.${hip_market}}})

Target cohort (all conditions must hold):
  1. Exists in Braze already — has an email SEND event AND a default-attributes
     profile. (/users/track never creates a new profile; we only ever send
     external_ids confirmed to exist.)
  2. Style-quiz home zip (ONBOARDING_ANSWER_HOME_ZIP_CODE) is in a HIP market —
     see data/hav_hip_zip_markets.yaml (single source of truth for zips + labels).
  3. Has NOT purchased a design package (no FIRST_DESIGN_PAYMENT, PAID_ROOMS = 0,
     TOTAL_NET_DESIGN_REVENUE = 0 in PROD.ANALYTICS.USER_FACTS) — equivalent to
     never having fired the Braze `design_fee` event.
  4. Email-reachable — has an email address and current global subscription
     status is not 'Unsubscribed'.
  5. Signed up in the last 6 months (USER_CREATED >= now - 6 months).

This is ~3,300-3,400 profiles (recent, mailable, non-purchaser HIP prospects).

Usage:
  uv run python scripts/sync_hav_hip_audience.py --dry-run   # preview only
  uv run python scripts/sync_hav_hip_audience.py             # write to Braze
  uv run python scripts/sync_hav_hip_audience.py --clear-stale  # also unset profiles no longer in cohort

Adapted from scripts/sync_hav_zip_codes.py.
"""

import argparse
import os
import sys
import time

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.snowflake_client import get_snowflake_client

BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY_HAV_USERS") or os.environ.get("BRAZE_API_KEY_HAV")
BRAZE_BASE_URL = os.environ.get("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com").rstrip("/")
BATCH_SIZE = 75  # Braze /users/track limit per request
HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"
DATASHARE_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
DATASHARE_SCHEMA = "DATALAKE_SHARING"

CROSSWALK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "hav_hip_zip_markets.yaml",
)


def load_crosswalk() -> dict[str, str]:
    """Return {zip5: market_display_name}. Fails loudly on any duplicate zip."""
    with open(CROSSWALK_PATH) as f:
        data = yaml.safe_load(f)
    zip_to_market: dict[str, str] = {}
    for market in data["markets"].values():
        display = market["display"]
        for z in market["zips"]:
            z = str(z).zfill(5)
            if z in zip_to_market:
                raise ValueError(f"zip {z} assigned to two markets: "
                                 f"{zip_to_market[z]} and {display}")
            zip_to_market[z] = display
    return zip_to_market


def _cohort_sql(zip_to_market: dict[str, str]) -> str:
    """Full SELECT returning (user_id, zip5) for the target cohort."""
    ds = f"{DATASHARE_DB}.{DATASHARE_SCHEMA}"
    in_list = ",".join(f"'{z}'" for z in sorted(zip_to_market))
    return f"""
        WITH braze_exists AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM {ds}.USERS_MESSAGES_EMAIL_SEND_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
        ),
        latest_sub AS (
            SELECT EXTERNAL_USER_ID, SUBSCRIPTION_STATUS
            FROM {ds}.USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}' AND EXTERNAL_USER_ID IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY EXTERNAL_USER_ID ORDER BY TIME DESC) = 1
        ),
        has_email AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM {ds}.USER_DEFAULT_ATTRIBUTES_VIEW_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND EMAIL_ADDRESS IS NOT NULL AND EMAIL_ADDRESS != ''
        ),
        cohort AS (
            SELECT uf.USER_ID::STRING AS user_id,
                   LEFT(TRIM(uf.ONBOARDING_ANSWER_HOME_ZIP_CODE), 5) AS zip5
            FROM PROD.ANALYTICS.USER_FACTS uf
            INNER JOIN braze_exists be ON uf.USER_ID::STRING = be.EXTERNAL_USER_ID
            INNER JOIN has_email he    ON uf.USER_ID::STRING = he.EXTERNAL_USER_ID
            LEFT JOIN  latest_sub ls   ON uf.USER_ID::STRING = ls.EXTERNAL_USER_ID
            WHERE LEFT(TRIM(uf.ONBOARDING_ANSWER_HOME_ZIP_CODE), 5) IN ({in_list})
              AND uf.FIRST_DESIGN_PAYMENT IS NULL
              AND COALESCE(uf.PAID_ROOMS, 0) = 0
              AND COALESCE(uf.TOTAL_NET_DESIGN_REVENUE, 0) = 0
              AND COALESCE(ls.SUBSCRIPTION_STATUS, 'Subscribed') <> 'Unsubscribed'
              AND uf.USER_CREATED >= DATEADD('month', -6, CURRENT_TIMESTAMP())
        )
        SELECT user_id, zip5 FROM cohort
    """


def fetch_cohort(zip_to_market: dict[str, str]) -> list[dict]:
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")
    rows = client.execute_query(_cohort_sql(zip_to_market))
    out = []
    for r in rows:
        market = zip_to_market.get(r["ZIP5"])
        if market:  # guard against any zip-normalization edge case
            out.append({"user_id": r["USER_ID"], "hip_market": market})
    return out


def fetch_stale(zip_to_market: dict[str, str]) -> list[str]:
    """Profiles currently flagged hip_eligible=true that are NOT in the cohort."""
    client = get_snowflake_client(schema="ANALYTICS", database="PROD")
    ds = f"{DATASHARE_DB}.{DATASHARE_SCHEMA}"
    query = f"""
        SELECT EXTERNAL_USER_ID AS user_id
        FROM {ds}.USER_CUSTOM_ATTRIBUTES_VIEW_SHARED cav
        WHERE cav.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND cav.CUSTOM_ATTRIBUTES:hip_eligible = TRUE
          AND cav.EXTERNAL_USER_ID NOT IN (
              SELECT user_id FROM ({_cohort_sql(zip_to_market)})
          )
    """
    return [r["USER_ID"] for r in client.execute_query(query)]


def push_to_braze(attributes: list[dict], dry_run: bool) -> int:
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
        return push_to_braze(attributes, dry_run)
    resp.raise_for_status()
    result = resp.json()
    errors = result.get("errors", [])
    if errors:
        print(f"  Braze errors: {errors}")
    return result.get("attributes_processed", len(attributes))


def _send_in_batches(attributes: list[dict], dry_run: bool, label: str) -> int:
    total = 0
    for i in range(0, len(attributes), BATCH_SIZE):
        batch = attributes[i:i + BATCH_SIZE]
        processed = push_to_braze(batch, dry_run)
        total += processed
        print(f"  {label} batch {i // BATCH_SIZE + 1}: {processed} attributes")
        if not dry_run and i + BATCH_SIZE < len(attributes):
            time.sleep(0.5)  # stay under Braze rate limit
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Braze.")
    parser.add_argument("--clear-stale", action="store_true",
                        help="Also set hip_eligible=false for profiles no longer in the cohort.")
    args = parser.parse_args()

    if not BRAZE_API_KEY:
        print("ERROR: BRAZE_API_KEY_HAV_USERS (or BRAZE_API_KEY_HAV) not set", file=sys.stderr)
        sys.exit(1)

    zip_to_market = load_crosswalk()
    print(f"Crosswalk: {len(zip_to_market)} qualifying zips across "
          f"{len(set(zip_to_market.values()))} markets")

    users = fetch_cohort(zip_to_market)
    print(f"Cohort: {len(users)} existing HAV Braze profiles "
          f"(recent, mailable, non-purchaser)")

    if users:
        by_market: dict[str, int] = {}
        for u in users:
            by_market[u["hip_market"]] = by_market.get(u["hip_market"], 0) + 1
        for m, n in sorted(by_market.items(), key=lambda x: -x[1]):
            print(f"    {m}: {n}")

        attrs = [
            {"external_id": u["user_id"], "hip_eligible": True, "hip_market": u["hip_market"]}
            for u in users
        ]
        written = _send_in_batches(attrs, args.dry_run, "flag")
        action = "would flag" if args.dry_run else "flagged"
        print(f"Done — {action} {written} profiles (hip_eligible=true + hip_market)")

    if args.clear_stale:
        stale = fetch_stale(zip_to_market)
        print(f"Stale: {len(stale)} profiles to unset (hip_eligible=false)")
        if stale:
            attrs = [{"external_id": uid, "hip_eligible": False} for uid in stale]
            written = _send_in_batches(attrs, args.dry_run, "clear")
            action = "would clear" if args.dry_run else "cleared"
            print(f"Done — {action} {written} stale profiles")


if __name__ == "__main__":
    main()

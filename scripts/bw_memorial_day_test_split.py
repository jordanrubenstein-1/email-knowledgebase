#!/usr/bin/env python3
"""
BW Memorial Day Canvas Test — Stratified List Split

Builds a stratified 30/30/40 test/control/excluded split from the BW May 2026
email audience and uploads a bw_memorial_day_test_group custom attribute to Braze.

Full list:    P_EM_2026_05_01_BW_D_Settle_Into_Spring_Sale_Reminder
Engaged list: P_EM_2026_05_02_BW_D_New_Arrivals_Outdoor_Roundup

Stratification strata (16 total: 2 × 4 × 2):
  - engaged:        on engaged list (0/1)
  - age_quartile:   Q1–Q4 of first-ever BW email send date
  - has_purchased:  any purchase in Braze datashare (0/1)

Within each stratum, users are sorted deterministically by MD5 hash of
external_user_id + seed, then split first-30% → test, next-30% → control,
last-40% → excluded. Same seed always produces the same assignment.

Usage:
  uv run python scripts/bw_memorial_day_test_split.py [--dry-run]

API key requirement:
  BRAZE_USERS_API_KEY_BW in .env with:
    - User Data: users.track
"""

import os
import sys
import time
import hashlib
import argparse
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowflake_client import get_snowflake_client

load_dotenv()

DB               = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA           = "DATALAKE_SHARING"
BUR_APP_GROUP_ID = "67093a1f24ebbe0065cb9c77"

FULL_LIST_CAMPAIGN_NAME    = "P_EM_2026_05_01_BW_D_Settle_Into_Spring_Sale_Reminder"
ENGAGED_LIST_CAMPAIGN_NAME = "P_EM_2026_05_02_BW_D_New_Arrivals_Outdoor_Roundup"

BRAZE_URL  = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
ATTR_NAME  = "bw_memorial_day_test_group"
SPLIT_SEED = "bw_memorial_day_2026"


# ---------------------------------------------------------------------------
# Task 2: Resolve campaign API IDs
# ---------------------------------------------------------------------------

def get_campaign_api_ids(names: list[str]) -> dict[str, str]:
    """Returns {campaign_name: api_id} for each name found in CHANGELOGS_CAMPAIGN_SHARED."""
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    name_list = ", ".join(f"'{n}'" for n in names)
    rows = client.execute_query(f"""
        SELECT NAME, API_ID
        FROM {DB}.{SCHEMA}.CHANGELOGS_CAMPAIGN_SHARED
        WHERE NAME IN ({name_list})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY NAME ORDER BY TIME DESC) = 1
    """)
    return {r["NAME"]: r["API_ID"] for r in rows}


# ---------------------------------------------------------------------------
# Task 3: Pull stratification features from Snowflake
# ---------------------------------------------------------------------------

def fetch_user_features(full_api_id: str, engaged_api_id: str) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per user in the full list who are currently
    email subscribed: external_user_id, user_id, engaged (0/1), first_send_date,
    has_purchased (0/1).

    Users with NULL external_user_id are excluded — cannot push to Braze by braze_id
    lookup without it. Users whose latest global subscription state is 'Unsubscribed'
    are excluded. Users with no subscription state record are kept (Braze default =
    subscribed).
    """
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    query = f"""
        WITH full_list AS (
            SELECT DISTINCT EXTERNAL_USER_ID, USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND CAMPAIGN_API_ID = '{full_api_id}'
              AND EXTERNAL_USER_ID IS NOT NULL
        ),
        latest_sub_state AS (
            SELECT USER_ID, SUBSCRIPTION_STATUS
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND CHANNEL = 'email'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY TIME DESC) = 1
        ),
        unsubscribed AS (
            SELECT USER_ID FROM latest_sub_state
            WHERE SUBSCRIPTION_STATUS = 'Unsubscribed'
        ),
        engaged_list AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND CAMPAIGN_API_ID = '{engaged_api_id}'
              AND EXTERNAL_USER_ID IS NOT NULL
        ),
        first_sends AS (
            SELECT h.EXTERNAL_USER_ID,
                   MIN(TO_TIMESTAMP(h.TIME)) AS first_send_date
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED h
            JOIN full_list f ON h.EXTERNAL_USER_ID = f.EXTERNAL_USER_ID
            WHERE h.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
            GROUP BY h.EXTERNAL_USER_ID
        ),
        purchases AS (
            SELECT DISTINCT p.USER_ID
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED p
            JOIN full_list f ON p.USER_ID = f.USER_ID
            WHERE p.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
        )
        SELECT
            f.EXTERNAL_USER_ID   AS external_user_id,
            f.USER_ID            AS user_id,
            CASE WHEN e.EXTERNAL_USER_ID IS NOT NULL THEN 1 ELSE 0 END AS engaged,
            fs.first_send_date,
            CASE WHEN p.USER_ID IS NOT NULL THEN 1 ELSE 0 END AS has_purchased
        FROM full_list f
        LEFT JOIN unsubscribed u ON f.USER_ID = u.USER_ID
        LEFT JOIN engaged_list e ON f.EXTERNAL_USER_ID = e.EXTERNAL_USER_ID
        LEFT JOIN first_sends fs ON f.EXTERNAL_USER_ID = fs.EXTERNAL_USER_ID
        LEFT JOIN purchases p    ON f.USER_ID = p.USER_ID
        WHERE u.USER_ID IS NULL
    """
    rows = client.execute_query(query)
    df = pd.DataFrame(rows)
    df.columns = [c.lower() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Task 4: Stratify and assign groups
# ---------------------------------------------------------------------------

def _hash_sort_key(external_id: str) -> int:
    """Deterministic sort key — same seed always produces same ordering."""
    return int(hashlib.md5(f"{SPLIT_SEED}:{external_id}".encode()).hexdigest(), 16)


def assign_groups(df: pd.DataFrame) -> pd.DataFrame:
    """
    Stratifies users into 16 strata (engaged × age_quartile × has_purchased)
    and assigns test/control/excluded (30/30/40) within each stratum.

    Assignment is deterministic — same input + SPLIT_SEED always produces
    the same result. Reproducible without storing a random state.
    """
    df = df.copy()

    # Fill missing first_send_date with the median (edge case: users with no send history)
    median_send = df["first_send_date"].median()
    df["first_send_date"] = df["first_send_date"].fillna(median_send)

    # Bucket account age into quartiles across the full list.
    # Convert to int64 (nanoseconds since epoch) for qcut — avoids timezone issues.
    df["age_quartile"] = pd.qcut(
        pd.to_datetime(df["first_send_date"]).astype("int64"),
        q=4,
        labels=[1, 2, 3, 4],
        duplicates="drop",
    ).astype(int)

    # Pre-compute hash sort keys for all users at once (faster than per-row lambda)
    df["_sort_key"] = df["external_user_id"].map(_hash_sort_key)

    df["group"] = ""

    strata_cols = ["engaged", "age_quartile", "has_purchased"]
    for _key, stratum_df in df.groupby(strata_cols):
        # Sort deterministically within this stratum
        sorted_idx = stratum_df.sort_values("_sort_key").index.tolist()
        n          = len(sorted_idx)
        n_test     = round(n * 0.30)
        n_control  = round(n * 0.30)

        df.loc[sorted_idx[:n_test],              "group"] = "test"
        df.loc[sorted_idx[n_test:n_test+n_control], "group"] = "control"
        df.loc[sorted_idx[n_test+n_control:],    "group"] = "excluded"

    df = df.drop(columns=["_sort_key"])
    return df


def print_balance(df: pd.DataFrame) -> None:
    now = pd.Timestamp.now(tz="UTC")
    header = f"{'Group':<12} {'Count':>8} {'% Engaged':>10} {'% Purchased':>12} {'Median Age':>12}"
    print(f"\n{header}")
    print("-" * 58)
    for group in ["test", "control", "excluded"]:
        g = df[df["group"] == group]
        send_dates = pd.to_datetime(g["first_send_date"], utc=True)
        median_days = (now - send_dates).dt.days.median()
        print(
            f"{group:<12} {len(g):>8,} {g['engaged'].mean():>10.1%} "
            f"{g['has_purchased'].mean():>12.1%} {median_days:>10.0f}d"
        )
    print()


# ---------------------------------------------------------------------------
# Task 5: Push attributes to Braze
# ---------------------------------------------------------------------------

def push_braze_attributes(records: list[dict], api_key: str) -> None:
    headers    = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url        = f"{BRAZE_URL}/users/track"
    batch_size = 75
    total_ok   = 0
    total_err  = 0

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        resp  = requests.post(url, json={"attributes": batch}, headers=headers, timeout=30)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"  Rate limited — sleeping {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(url, json={"attributes": batch}, headers=headers, timeout=30)

        resp.raise_for_status()
        data   = resp.json()
        errors = data.get("errors", [])
        total_err += len(errors)
        total_ok  += len(batch) - len(errors)

        if errors:
            print(f"  Batch {i // batch_size + 1}: {len(errors)} errors: {errors[:2]}")
        elif (i // batch_size + 1) % 50 == 0 or i == 0:
            print(f"  Batch {i // batch_size + 1}: {total_ok:,} pushed so far...")

        time.sleep(0.1)  # stay well under 250 req/min

    print(f"  Done. {total_ok:,} pushed OK, {total_err} errors.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build stratified 30/30/40 BW Memorial Day test split and push to Braze"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Query and stratify but skip Braze push")
    args = parser.parse_args()

    api_key = os.environ.get("BRAZE_USERS_API_KEY_BW")
    if not api_key and not args.dry_run:
        print("ERROR: BRAZE_USERS_API_KEY_BW not set in .env")
        print("  Create a Braze API key in the BW workspace with: User Data > users.track")
        sys.exit(1)

    # ── Task 2: Resolve campaign API IDs ────────────────────────────────────
    print("Resolving campaign API IDs from Snowflake...")
    api_ids = get_campaign_api_ids([FULL_LIST_CAMPAIGN_NAME, ENGAGED_LIST_CAMPAIGN_NAME])

    if FULL_LIST_CAMPAIGN_NAME not in api_ids:
        print(f"ERROR: '{FULL_LIST_CAMPAIGN_NAME}' not found in CHANGELOGS_CAMPAIGN_SHARED")
        sys.exit(1)
    if ENGAGED_LIST_CAMPAIGN_NAME not in api_ids:
        print(f"ERROR: '{ENGAGED_LIST_CAMPAIGN_NAME}' not found in CHANGELOGS_CAMPAIGN_SHARED")
        sys.exit(1)

    full_api_id    = api_ids[FULL_LIST_CAMPAIGN_NAME]
    engaged_api_id = api_ids[ENGAGED_LIST_CAMPAIGN_NAME]
    print(f"  Full list API ID:    {full_api_id}")
    print(f"  Engaged list API ID: {engaged_api_id}")

    # ── Task 3: Pull features ────────────────────────────────────────────────
    print("\nFetching user features from Snowflake (this may take a minute)...")
    df = fetch_user_features(full_api_id, engaged_api_id)
    print(f"  Full list:            {len(df):,} users")
    print(f"  On engaged list:      {df['engaged'].sum():,} ({df['engaged'].mean():.1%})")
    print(f"  Have purchased:       {df['has_purchased'].sum():,} ({df['has_purchased'].mean():.1%})")
    print(f"  Missing first_send:   {df['first_send_date'].isna().sum():,}")

    # ── Task 4: Stratify and assign ──────────────────────────────────────────
    print("\nAssigning stratified groups...")
    df = assign_groups(df)

    counts = df["group"].value_counts()
    total  = len(df)
    print(f"  test:     {counts.get('test', 0):,} ({counts.get('test', 0)/total:.1%})")
    print(f"  control:  {counts.get('control', 0):,} ({counts.get('control', 0)/total:.1%})")
    print(f"  excluded: {counts.get('excluded', 0):,} ({counts.get('excluded', 0)/total:.1%})")

    print_balance(df)

    # Save audit CSV regardless of dry-run
    out_path = Path("exports/bw_memorial_day_test_assignments.csv")
    out_path.parent.mkdir(exist_ok=True)
    df[["external_user_id", "group", "engaged", "age_quartile", "has_purchased"]].to_csv(
        out_path, index=False
    )
    print(f"Assignments saved to {out_path}")

    # ── Task 5: Push to Braze ────────────────────────────────────────────────
    if args.dry_run:
        print("\n[dry-run] Skipping Braze push. Sample assignments per group:")
        sample = df.groupby("group").head(2)[["external_user_id", "group"]]
        print(sample.to_string(index=False))
        return

    print(f"\nPushing '{ATTR_NAME}' attribute for {len(df):,} users to Braze...")
    # Use braze_id (Braze's internal user_id) rather than external_id.
    # braze_id only matches existing profiles — can never create duplicate users.
    attributes = [
        {"braze_id": row["user_id"], ATTR_NAME: row["group"]}
        for row in df[["user_id", "group"]].to_dict("records")
    ]
    push_braze_attributes(attributes, api_key)
    print("\nAll done.")


if __name__ == "__main__":
    main()

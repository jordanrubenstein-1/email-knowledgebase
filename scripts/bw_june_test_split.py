#!/usr/bin/env python3
"""
BW June Canvas Test — Stratified List Split

Builds a stratified 1%/99% test/control split from the BW June 2 email audience
and uploads a bw_june_test_group custom attribute to Braze.

Audience:  Users who received any of:
  - P_EM_2026_06_02_BW_PT_Memorial_Day_Final_Hours (campaign 1, stopped mid-flight)
  - P_EM_2026_06_02_BW_PT_Memorial_Day_Final_Hours (campaign 2, re-send to remainder)
  - Canvas step P_EM_2026_BW_PT_TPA_T23_Extension_Last_Day_PM

Stratification strata (48 total: 2 × 2 × 3 × 4):
  - engaged:       behavioral — clicked/opened/purchased/events/age signals (0/1)
  - has_purchased: any BW purchase all-time in datashare (0/1)
  - mds_group:     'test'/'control'/'neither' from MDS CSV (or not in CSV → 'neither')
  - age_quartile:  Q1–Q4 of first-ever BW email send date (proxy for account age)

Within each stratum users are sorted by MD5(SPLIT_SEED + ":" + external_user_id),
then the first 1% → "test", remaining 99% → "control". Same seed always produces
the same assignment (fully deterministic without storing random state).

Usage:
  uv run python scripts/bw_june_test_split.py [--dry-run]

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

# Audience sources
CAMPAIGN_API_ID_1     = "c770674a-c367-40f1-ab9a-4ddc3f55c89f"  # final-hours re-send (145,838 sends) — sent after stopping the first
CAMPAIGN_API_ID_2     = "54152364-2d9c-4ab8-bc70-56c205204db8"  # final-hours original send (17,566 sends) — stopped mid-flight June 1
CANVAS_ID             = "69f261a5ccd10100817a4412"              # MDS Tentpole Automation (internal hex ID — NOT the REST API UUID from YAMLs)
CANVAS_STEP_API_ID    = "8f2f09c5-fd1b-4805-ba41-d5d83a3af50b"  # T23 Extension Last Day PM

# Fixed cutoff for reproducible engagement windows — do NOT use CURRENT_TIMESTAMP()
CUTOFF_DATE = "2026-06-04"

BRAZE_URL  = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
ATTR_NAME  = "bw_june_test_group"
SPLIT_SEED = "bw_june_2026"  # different seed from MDS to prevent correlation
TEST_PCT   = 0.01

MDS_CSV_PATH = Path("exports/bw_memorial_day_test_assignments.csv")


# ---------------------------------------------------------------------------
# Fetch user features from Snowflake
# ---------------------------------------------------------------------------

def fetch_user_features() -> pd.DataFrame:
    """
    Returns one row per distinct subscribed user who received any of the 3 source sends.
    Columns: external_user_id, user_id, first_send_date, has_purchased,
             engaged_signals (0/1 — all behavioral signals except age, which is added in Python).

    Subscription filter: users whose latest global email sub state is 'Unsubscribed' are excluded.
    Users with NULL external_user_id are excluded (cannot push to Braze by braze_id without it).
    """
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    query = f"""
        WITH audience AS (
            -- Union all three send sources; DISTINCT on (external_user_id, user_id)
            SELECT DISTINCT EXTERNAL_USER_ID, USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IS NOT NULL
              AND (
                CAMPAIGN_API_ID IN ('{CAMPAIGN_API_ID_1}', '{CAMPAIGN_API_ID_2}')
                OR (
                  CANVAS_ID = '{CANVAS_ID}'
                  AND CANVAS_STEP_API_ID = '{CANVAS_STEP_API_ID}'
                )
              )
        ),
        latest_sub_state AS (
            -- Keep only the most recent global email subscription state per user
            SELECT USER_ID, SUBSCRIPTION_STATUS
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND CHANNEL = 'email'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY TIME DESC) = 1
        ),
        unsubscribed AS (
            SELECT USER_ID FROM latest_sub_state WHERE SUBSCRIPTION_STATUS = 'Unsubscribed'
        ),
        first_sends AS (
            -- Oldest BW email send date per user — proxy for account creation date
            SELECT h.EXTERNAL_USER_ID,
                   MIN(TO_TIMESTAMP(h.TIME)) AS first_send_date
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED h
            JOIN audience a ON h.EXTERNAL_USER_ID = a.EXTERNAL_USER_ID
            WHERE h.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
            GROUP BY h.EXTERNAL_USER_ID
        ),
        purchases_alltime AS (
            -- Any BW purchase ever (for has_purchased stratification dimension)
            SELECT DISTINCT p.USER_ID
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED p
            JOIN audience a ON p.USER_ID = a.USER_ID
            WHERE p.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
        ),
        -- ── Engagement signals ────────────────────────────────────────────────
        eng_clicks AS (
            -- Clicked any BW email in last 183 days
            SELECT DISTINCT c.USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
            JOIN audience a ON c.USER_ID = a.USER_ID
            WHERE c.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND TO_TIMESTAMP(c.TIME) >= DATEADD('day', -183, '{CUTOFF_DATE}'::DATE)
        ),
        eng_opens AS (
            -- Non-machine-opened any BW email in last 183 days
            -- MACHINE_OPEN is a STRING column: 'true' or NULL (no 'false' values)
            SELECT DISTINCT o.USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED o
            JOIN audience a ON o.USER_ID = a.USER_ID
            WHERE o.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND o.MACHINE_OPEN IS NULL
              AND TO_TIMESTAMP(o.TIME) >= DATEADD('day', -183, '{CUTOFF_DATE}'::DATE)
        ),
        eng_purchases AS (
            -- Purchased in last 366 days
            SELECT DISTINCT p.USER_ID
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED p
            JOIN audience a ON p.USER_ID = a.USER_ID
            WHERE p.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND TO_TIMESTAMP(p.TIME) >= DATEADD('day', -366, '{CUTOFF_DATE}'::DATE)
        ),
        eng_checkout AS (
            -- Did 'Completed Checkout Step' custom event in last 366 days
            SELECT DISTINCT e.USER_ID
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED e
            JOIN audience a ON e.USER_ID = a.USER_ID
            WHERE e.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND e.NAME = 'Completed Checkout Step'
              AND TO_TIMESTAMP(e.TIME) >= DATEADD('day', -366, '{CUTOFF_DATE}'::DATE)
        ),
        eng_product_added AS (
            -- Last did 'Product Added' custom event in last 183 days
            SELECT DISTINCT e.USER_ID
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED e
            JOIN audience a ON e.USER_ID = a.USER_ID
            WHERE e.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND e.NAME = 'Product Added'
              AND TO_TIMESTAMP(e.TIME) >= DATEADD('day', -183, '{CUTOFF_DATE}'::DATE)
        )
        SELECT
            a.EXTERNAL_USER_ID                                          AS external_user_id,
            a.USER_ID                                                   AS user_id,
            fs.first_send_date,
            CASE WHEN pa.USER_ID  IS NOT NULL THEN 1 ELSE 0 END        AS has_purchased,
            -- engaged_signals: OR of all datashare-computable signals
            -- The "created at < 60 days" age signal is added in Python via first_send_date
            CASE WHEN (
                ec.USER_ID  IS NOT NULL OR
                eo.USER_ID  IS NOT NULL OR
                ep.USER_ID  IS NOT NULL OR
                eck.USER_ID IS NOT NULL OR
                epa.USER_ID IS NOT NULL
            ) THEN 1 ELSE 0 END                                         AS engaged_signals
        FROM audience a
        LEFT JOIN unsubscribed   u   ON a.USER_ID          = u.USER_ID
        LEFT JOIN first_sends    fs  ON a.EXTERNAL_USER_ID = fs.EXTERNAL_USER_ID
        LEFT JOIN purchases_alltime pa ON a.USER_ID        = pa.USER_ID
        LEFT JOIN eng_clicks     ec  ON a.USER_ID          = ec.USER_ID
        LEFT JOIN eng_opens      eo  ON a.USER_ID          = eo.USER_ID
        LEFT JOIN eng_purchases  ep  ON a.USER_ID          = ep.USER_ID
        LEFT JOIN eng_checkout   eck ON a.USER_ID          = eck.USER_ID
        LEFT JOIN eng_product_added epa ON a.USER_ID       = epa.USER_ID
        WHERE u.USER_ID IS NULL  -- drop unsubscribed
    """
    rows = client.execute_query(query)
    df = pd.DataFrame(rows)
    df.columns = [c.lower() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Load MDS group assignments from prior CSV
# ---------------------------------------------------------------------------

def load_mds_groups() -> dict[str, str]:
    """
    Returns {external_user_id: mds_group} where mds_group is 'test', 'control',
    or 'neither'. Users with group='excluded' map to 'neither'.
    """
    if not MDS_CSV_PATH.exists():
        print(f"  WARNING: {MDS_CSV_PATH} not found — all users will be assigned mds_group='neither'")
        return {}
    mds = pd.read_csv(MDS_CSV_PATH, usecols=["external_user_id", "group"])
    mapping = {}
    for _, row in mds.iterrows():
        val = row["group"]
        mapping[row["external_user_id"]] = val if val in ("test", "control") else "neither"
    return mapping


# ---------------------------------------------------------------------------
# Stratify and assign groups
# ---------------------------------------------------------------------------

def _hash_sort_key(external_id: str) -> int:
    """Deterministic sort key — same seed always produces same ordering."""
    return int(hashlib.md5(f"{SPLIT_SEED}:{external_id}".encode()).hexdigest(), 16)


def assign_groups(df: pd.DataFrame, mds_map: dict[str, str]) -> pd.DataFrame:
    """
    Stratifies users into 48 strata (engaged × has_purchased × mds_group × age_quartile)
    and assigns test (1%) / control (99%) within each stratum.

    Assignment is deterministic — same input + SPLIT_SEED always produces the same result.
    """
    df = df.copy()
    cutoff = pd.Timestamp(CUTOFF_DATE, tz="UTC")

    # Fill missing first_send_date with the median (edge case: new users with no prior send)
    median_send = df["first_send_date"].median()
    df["first_send_date"] = df["first_send_date"].fillna(median_send)

    # Finalize engaged flag: combine SQL signals with the age proxy
    # "created at < 60 days ago" ≈ first BW email send < 60 days before cutoff
    send_dates = pd.to_datetime(df["first_send_date"], utc=True)
    age_signal = (send_dates >= cutoff - pd.Timedelta(days=60)).astype(int)
    df["engaged"] = ((df["engaged_signals"] == 1) | (age_signal == 1)).astype(int)

    # Age quartile across the full list (Q1 = oldest, Q4 = newest)
    df["age_quartile"] = pd.qcut(
        pd.to_datetime(df["first_send_date"]).astype("int64"),
        q=4,
        labels=[1, 2, 3, 4],
        duplicates="drop",
    ).astype(int)

    # MDS group from prior CSV join
    df["mds_group"] = df["external_user_id"].map(mds_map).fillna("neither")

    # Pre-compute hash sort keys (faster than per-row lambda)
    df["_sort_key"] = df["external_user_id"].map(_hash_sort_key)

    df["group"] = ""

    strata_cols = ["engaged", "has_purchased", "mds_group", "age_quartile"]
    for _key, stratum_df in df.groupby(strata_cols):
        sorted_idx = stratum_df.sort_values("_sort_key").index.tolist()
        n          = len(sorted_idx)
        n_test     = max(1, round(n * TEST_PCT))  # at least 1 test user per stratum

        df.loc[sorted_idx[:n_test], "group"]  = "test"
        df.loc[sorted_idx[n_test:], "group"]  = "control"

    df = df.drop(columns=["_sort_key", "engaged_signals"])
    return df


def print_balance(df: pd.DataFrame) -> None:
    """Print a balance table comparing test and control across all stratification dimensions."""
    now = pd.Timestamp.now(tz="UTC")
    print(f"\n{'Group':<10} {'Count':>8} {'%Engaged':>9} {'%Purch':>8} {'MDS-test':>9} {'MDS-ctrl':>9} {'MDS-none':>9} {'Med.Age':>9}")
    print("-" * 80)
    for group in ["test", "control"]:
        g = df[df["group"] == group]
        send_dates = pd.to_datetime(g["first_send_date"], utc=True)
        median_days = (now - send_dates).dt.days.median()
        mds = g["mds_group"].value_counts(normalize=True)
        print(
            f"{group:<10} {len(g):>8,} {g['engaged'].mean():>9.1%} "
            f"{g['has_purchased'].mean():>8.1%} "
            f"{mds.get('test', 0):>9.1%} {mds.get('control', 0):>9.1%} {mds.get('neither', 0):>9.1%} "
            f"{median_days:>8.0f}d"
        )
    print()


# ---------------------------------------------------------------------------
# Push attributes to Braze
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
        description="Build stratified 1%/99% BW June test split and push to Braze"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Query and stratify but skip Braze push")
    args = parser.parse_args()

    api_key = os.environ.get("BRAZE_USERS_API_KEY_BW")
    if not api_key and not args.dry_run:
        print("ERROR: BRAZE_USERS_API_KEY_BW not set in .env")
        print("  Create a Braze API key in the BW workspace with: User Data > users.track")
        sys.exit(1)

    # ── Fetch features ───────────────────────────────────────────────────────
    print("Fetching user features from Snowflake (this may take a few minutes)...")
    df = fetch_user_features()
    print(f"  Audience (subscribed, non-null ext ID): {len(df):,} users")
    print(f"  Engaged signals (SQL):                  {df['engaged_signals'].sum():,} ({df['engaged_signals'].mean():.1%})")
    print(f"  Have purchased (all-time):              {df['has_purchased'].sum():,} ({df['has_purchased'].mean():.1%})")
    print(f"  Missing first_send_date:                {df['first_send_date'].isna().sum():,}")

    # ── Load MDS groups ──────────────────────────────────────────────────────
    print(f"\nLoading MDS group assignments from {MDS_CSV_PATH}...")
    mds_map = load_mds_groups()
    print(f"  MDS CSV entries loaded: {len(mds_map):,}")

    # ── Stratify and assign ──────────────────────────────────────────────────
    print("\nAssigning stratified groups...")
    df = assign_groups(df, mds_map)

    counts = df["group"].value_counts()
    total  = len(df)
    print(f"  test:    {counts.get('test', 0):,} ({counts.get('test', 0)/total:.2%})")
    print(f"  control: {counts.get('control', 0):,} ({counts.get('control', 0)/total:.2%})")
    print(f"\n  Engaged (post age-signal merge): {df['engaged'].sum():,} ({df['engaged'].mean():.1%})")
    mds_dist = df["mds_group"].value_counts()
    print(f"  MDS groups — test: {mds_dist.get('test',0):,}  control: {mds_dist.get('control',0):,}  neither: {mds_dist.get('neither',0):,}")

    print_balance(df)

    # ── Save audit CSV regardless of dry-run ─────────────────────────────────
    out_path = Path("exports/bw_june_test_assignments.csv")
    out_path.parent.mkdir(exist_ok=True)
    df[["external_user_id", "group", "engaged", "has_purchased", "mds_group", "age_quartile"]].to_csv(
        out_path, index=False
    )
    print(f"Assignments saved to {out_path}")

    # ── Push to Braze ────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[dry-run] Skipping Braze push. Sample assignments per group:")
        sample = df.groupby("group").head(3)[["external_user_id", "group", "engaged", "mds_group"]]
        print(sample.to_string(index=False))
        return

    print(f"\nPushing '{ATTR_NAME}' attribute for {len(df):,} users to Braze...")
    attributes = [
        {"braze_id": row["user_id"], ATTR_NAME: row["group"]}
        for row in df[["user_id", "group"]].to_dict("records")
    ]
    push_braze_attributes(attributes, api_key)
    print("\nAll done.")


if __name__ == "__main__":
    main()

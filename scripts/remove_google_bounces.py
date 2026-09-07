#!/usr/bin/env python3
"""
Remove hard bounce status for @havenly.com addresses affected by the Google
Workspace contract lapse on 2026-04-05 and 2026-04-06.

Usage:
    # Preview only — writes CSV, no API calls
    uv run python scripts/remove_google_bounces.py --dry-run

    # Remove bounces (full run)
    uv run python scripts/remove_google_bounces.py --no-dry-run

    # Test with a small batch first
    uv run python scripts/remove_google_bounces.py --no-dry-run --limit 10

    # Re-run from previously exported CSV (skip Snowflake)
    uv run python scripts/remove_google_bounces.py --no-dry-run --from-csv exports/google_bounce_recovery_2026-04-07.csv
"""

import argparse
import csv
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from import_braze import init_config, get_api_key, get_base_url
from snowflake_client import get_snowflake_client

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_EXPORTS_DIR = _PROJECT_ROOT / "exports"
_CSV_PATH = _EXPORTS_DIR / "google_bounce_recovery_2026-04-07.csv"

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"

# Incident window: Google contract lapse caused bounces on these dates
INCIDENT_START = "2026-04-05"
INCIDENT_END = "2026-04-06"


def discover_email_column(client) -> str:
    """Return the column name for recipient email in the bounce view."""
    rows = client.execute_query(
        f"DESCRIBE VIEW {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED"
    )
    col_names = [r.get("name", "").upper() for r in rows]
    for candidate in ("EMAIL_ADDRESS", "TO_EMAIL", "EMAIL"):
        if candidate in col_names:
            return candidate
    print(f"ERROR: Could not find email column. Available columns: {col_names}")
    sys.exit(1)


def query_affected_users(client, email_col: str) -> list[dict]:
    """Query Snowflake for @havenly.com addresses that bounced during the incident
    but had NOT bounced before the incident window."""
    query = f"""
        WITH incident_bounces AS (
            SELECT DISTINCT
                EXTERNAL_USER_ID,
                {email_col} AS EMAIL_ADDRESS
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{INCIDENT_START}' AND '{INCIDENT_END}'
              AND {email_col} ILIKE '%@havenly.com'
        ),
        prior_bouncers AS (
            SELECT DISTINCT EXTERNAL_USER_ID
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_TIMESTAMP(TIME) < '{INCIDENT_START}'
              AND {email_col} ILIKE '%@havenly.com'
              AND EXTERNAL_USER_ID IS NOT NULL
        )
        SELECT
            ib.EXTERNAL_USER_ID,
            ib.EMAIL_ADDRESS
        FROM incident_bounces ib
        LEFT JOIN prior_bouncers pb ON ib.EXTERNAL_USER_ID = pb.EXTERNAL_USER_ID
        WHERE pb.EXTERNAL_USER_ID IS NULL
        ORDER BY ib.EMAIL_ADDRESS
    """
    return client.execute_query(query)


def write_csv(rows: list[dict]) -> None:
    """Write affected users to CSV for audit trail."""
    _EXPORTS_DIR.mkdir(exist_ok=True)
    with open(_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["EXTERNAL_USER_ID", "EMAIL_ADDRESS"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV written: {_CSV_PATH} ({len(rows)} rows)")


def load_csv() -> list[dict]:
    """Load affected users from a previously exported CSV."""
    with open(_CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def remove_bounce(email: str, api_key: str, base_url: str) -> bool:
    """Remove hard bounce status for one email address. Returns True on success."""
    try:
        resp = requests.post(
            f"{base_url}/email/bounce/remove",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"email": email},
            timeout=15,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"  Rate limited — sleeping {retry_after}s")
            time.sleep(retry_after)
            # Retry once after sleeping
            resp = requests.post(
                f"{base_url}/email/bounce/remove",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"email": email},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ERROR removing bounce for {email}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Remove Google-lapse hard bounces for @havenly.com users")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Query Snowflake + write CSV only, no API calls")
    mode.add_argument("--no-dry-run", action="store_true", help="Execute bounce removals via Braze API")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of bounce removals (for testing)")
    parser.add_argument("--from-csv", metavar="PATH", help="Load emails from CSV instead of querying Snowflake")
    args = parser.parse_args()

    # --- Phase 1: Get the list of affected users ---
    if args.from_csv:
        csv_path = Path(args.from_csv)
        if not csv_path.exists():
            print(f"ERROR: CSV not found: {csv_path}")
            sys.exit(1)
        rows = list(csv.DictReader(open(csv_path, newline="")))
        print(f"Loaded {len(rows)} rows from {csv_path}")
    else:
        print("Connecting to Snowflake…")
        client = get_snowflake_client(schema=SCHEMA, database=DB)

        print("Discovering email column in bounce view…")
        email_col = discover_email_column(client)
        print(f"  Email column: {email_col}")

        print(f"Querying bounces between {INCIDENT_START} and {INCIDENT_END}…")
        rows = query_affected_users(client, email_col)
        print(f"Found {len(rows)} @havenly.com users who bounced during the incident and had no prior bounces.")

        write_csv(rows)

    if not rows:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("Dry run complete. Re-run with --no-dry-run to remove bounces.")
        return

    # --- Phase 2: Remove bounce status via Braze API ---
    init_config("HAV")
    api_key = get_api_key()
    base_url = get_base_url()

    targets = rows[: args.limit] if args.limit else rows
    print(f"\nRemoving bounce status for {len(targets)} users via Braze API…")
    if args.limit:
        print(f"  (limited to first {args.limit} of {len(rows)} total)")

    successes = 0
    failures = 0
    for i, row in enumerate(targets, 1):
        email = row.get("EMAIL_ADDRESS") or row.get("email_address") or ""
        if not email:
            print(f"  [{i}/{len(targets)}] Skipping row with no email: {row}")
            failures += 1
            continue

        ok = remove_bounce(email, api_key, base_url)
        status = "OK" if ok else "FAIL"
        print(f"  [{i}/{len(targets)}] {status}  {email}")
        if ok:
            successes += 1
        else:
            failures += 1
        time.sleep(0.05)  # ~20 req/sec

    print(f"\nDone. Removed: {successes}  Failed: {failures}")
    if failures:
        print("Check output above for failed emails — you may re-run with --from-csv after fixing.")


if __name__ == "__main__":
    main()

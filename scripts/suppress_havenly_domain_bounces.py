#!/usr/bin/env python3
"""
Suppress @havenly.com addresses that have been soft-bouncing in Braze.

Targets the "safe" pre-April-6 cohort: addresses whose first soft bounce
predates the April 6 Google Workspace policy change, strongly indicating
deactivated accounts rather than active-employee policy blocks.

Usage:
    # Dry run — shows what would be suppressed, touches nothing
    uv run python scripts/suppress_havenly_domain_bounces.py --dry-run

    # Live run — unsubscribes addresses in all applicable workspaces
    uv run python scripts/suppress_havenly_domain_bounces.py

    # Single brand only
    uv run python scripts/suppress_havenly_domain_bounces.py --brand HAV

    # Use blocklist instead of unsubscribe (stronger — prevents re-subscribe)
    uv run python scripts/suppress_havenly_domain_bounces.py --mode blocklist

    # Run against the verify-first (Apr 6+) group instead (use after HR confirms)
    uv run python scripts/suppress_havenly_domain_bounces.py --cohort verify
"""

import os
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.snowflake_client import get_snowflake_client

# ── Braze config ────────────────────────────────────────────────────────────
BRANDS = {
    "BUR": {
        "api_key": os.environ.get("BRAZE_API_KEY_BUR"),
        "api_url": os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com"),
        "app_group_id": "67093a1f24ebbe0065cb9c77",
    },
    "HAV": {
        "api_key": os.environ.get("BRAZE_API_KEY_HAV"),
        "api_url": os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com"),
        "app_group_id": "664223fb71bcf3005760dfc2",
    },
    "CZ": {
        "api_key": os.environ.get("BRAZE_API_KEY_CZ"),
        "api_url": os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com"),
        "app_group_id": "666672a4d8965b005ac6c1bd",
    },
}

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"

# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_candidates(cohort: str) -> dict[str, list[str]]:
    """
    Returns {brand: [email, ...]} for the requested cohort.

    cohort='suppress' → first bounce before April 6 (safe, deactivated)
    cohort='verify'   → first bounce April 6+ (needs HR sign-off first)
    """
    cutoff = "'2026-04-06'"
    date_filter = f"< {cutoff}" if cohort == "suppress" else f">= {cutoff}"

    app_ids = "', '".join(cfg["app_group_id"] for cfg in BRANDS.values())
    id_to_brand = {cfg["app_group_id"]: brand for brand, cfg in BRANDS.items()}

    client = get_snowflake_client(schema=SCHEMA, database=DB)

    q = f"""
    WITH first_bounce AS (
        SELECT
            APP_GROUP_ID,
            EMAIL_ADDRESS,
            EXTERNAL_USER_ID,
            MIN(TO_TIMESTAMP(TIME)) as first_bounce_ever
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
        WHERE APP_GROUP_ID IN ('{app_ids}')
          AND LOWER(EMAIL_ADDRESS) LIKE '%@havenly.com'
          AND EMAIL_ADDRESS NOT LIKE '%deleted-customer%'
          AND EMAIL_ADDRESS NOT LIKE '%+%@havenly.com'
          AND EMAIL_ADDRESS NOT IN (
              'abuse@havenly.com','noreply@havenly.com','do-not-reply@havenly.com',
              'customersupport@havenly.com','orders1@havenly.com','creativeteam@havenly.com',
              'sarah2testing@havenly.com','testing-codes@havenly.com','testingsarah@havenly.com'
          )
        GROUP BY 1, 2, 3
    )
    SELECT APP_GROUP_ID, EMAIL_ADDRESS, EXTERNAL_USER_ID
    FROM first_bounce
    WHERE first_bounce_ever {date_filter}
    ORDER BY APP_GROUP_ID, EMAIL_ADDRESS
    """
    rows = client.execute_query(q)

    # Deduplicate — same email can have multiple Braze user records
    result = defaultdict(set)
    for r in rows:
        brand = id_to_brand.get(r["APP_GROUP_ID"])
        if brand:
            result[brand].add(r["EMAIL_ADDRESS"])
    return {brand: sorted(emails) for brand, emails in result.items()}


def braze_post(brand: str, endpoint: str, payload: dict, dry_run: bool) -> dict:
    cfg = BRANDS[brand]
    url = f"{cfg['api_url'].rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    if dry_run:
        print(f"    [DRY RUN] POST {url}")
        print(f"    Payload: {json.dumps(payload)[:200]}")
        return {"message": "dry_run"}

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def chunked(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


# Brands whose API keys have /users/track permission (batch, 75/call)
USERS_TRACK_BRANDS = {"BUR"}

def suppress_via_unsubscribe(brand: str, emails: list[str], dry_run: bool):
    """
    Sets subscription status to unsubscribed.
    - BUR: /users/track  (75 per call — batch)
    - HAV, CZ: /email/status  (1 per call — sequential, but these keys lack users.track)
    """
    if brand in USERS_TRACK_BRANDS:
        return _unsubscribe_users_track(brand, emails, dry_run)
    else:
        return _unsubscribe_email_status(brand, emails, dry_run)


def _unsubscribe_users_track(brand: str, emails: list[str], dry_run: bool):
    """Sets email_subscribe = 'unsubscribed' via /users/track (75/call)."""
    print(f"\n  [{brand}] Unsubscribing {len(emails)} addresses via /users/track …")
    success = 0
    for batch in chunked(emails, 75):
        attributes = [{"email": email, "email_subscribe": "unsubscribed"} for email in batch]
        result = braze_post(brand, "/users/track", {"attributes": attributes}, dry_run)
        if not dry_run:
            errors = result.get("errors", [])
            if errors:
                print(f"    ⚠️  Errors in batch: {errors}")
            else:
                success += len(batch)
                print(f"    ✓ {len(batch)} addresses unsubscribed")
            time.sleep(0.5)
        else:
            success += len(batch)
    return success


def _unsubscribe_email_status(brand: str, emails: list[str], dry_run: bool):
    """Sets subscription_state = 'unsubscribed' via /email/status (1 per call)."""
    print(f"\n  [{brand}] Unsubscribing {len(emails)} addresses via /email/status …")
    success = 0
    errors = []
    for i, email in enumerate(emails, 1):
        result = braze_post(brand, "/email/status",
                            {"email": email, "subscription_state": "unsubscribed"}, dry_run)
        if not dry_run:
            if result.get("message") == "success":
                success += 1
            else:
                errors.append(f"{email}: {result}")
            if i % 10 == 0:
                print(f"    … {i}/{len(emails)}")
            time.sleep(0.25)  # /email/status has no stated batch limit; be conservative
        else:
            success += 1
    if errors:
        print(f"    ⚠️  {len(errors)} errors: {errors[:3]}")
    if not dry_run:
        print(f"    ✓ {success}/{len(emails)} addresses unsubscribed")
    return success


def suppress_via_blocklist(brand: str, emails: list[str], dry_run: bool):
    """
    Adds addresses to the Braze global email blocklist via /email/blocklist.
    Braze accepts up to 50 emails per call.
    """
    print(f"\n  [{brand}] Adding {len(emails)} addresses to blocklist via /email/blocklist …")
    success = 0
    for batch in chunked(emails, 50):
        result = braze_post(brand, "/email/blocklist", {"email": batch}, dry_run)
        if not dry_run:
            if result.get("message") == "success":
                success += len(batch)
                print(f"    ✓ {len(batch)} addresses blocklisted")
            else:
                print(f"    ⚠️  Unexpected response: {result}")
            time.sleep(0.5)
        else:
            success += len(batch)
    return success


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Suppress bouncing @havenly.com addresses in Braze")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be suppressed without making any API calls")
    parser.add_argument("--brand", choices=["BUR", "HAV", "CZ"],
                        help="Target a single brand workspace (default: all three)")
    parser.add_argument("--mode", choices=["unsubscribe", "blocklist"], default="unsubscribe",
                        help="unsubscribe = set email_subscribe=unsubscribed; "
                             "blocklist = add to global Braze email blocklist (stronger)")
    parser.add_argument("--cohort", choices=["suppress", "verify"], default="suppress",
                        help="suppress = pre-Apr-6 safe cohort (default); "
                             "verify = Apr-6+ cohort (use only after HR confirms inactive)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompts (for scripted use)")
    args = parser.parse_args()

    if args.cohort == "verify":
        print("⚠️  WARNING: Running against the 'verify first' cohort.")
        print("   This group includes active employees who are Google-policy-blocked.")
        print("   Only proceed if HR has confirmed these addresses are inactive.")
        confirm = input("   Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

    print(f"Fetching {args.cohort} cohort from Snowflake …")
    candidates = fetch_candidates(args.cohort)

    if args.brand:
        candidates = {args.brand: candidates.get(args.brand, [])}

    total = sum(len(v) for v in candidates.values())
    unique = len(set(e for emails in candidates.values() for e in emails))
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Suppression plan:")
    print(f"  Mode:   {args.mode}")
    print(f"  Cohort: {args.cohort}")
    print(f"  Total brand-address pairs: {total}")
    print(f"  Unique addresses:          {unique}")
    for brand, emails in sorted(candidates.items()):
        print(f"    {brand}: {len(emails)}")

    if not args.dry_run and not args.yes:
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

    total_suppressed = 0
    for brand, emails in sorted(candidates.items()):
        if not emails:
            print(f"\n  [{brand}] No candidates — skipping.")
            continue
        if args.mode == "unsubscribe":
            n = suppress_via_unsubscribe(brand, emails, args.dry_run)
        else:
            n = suppress_via_blocklist(brand, emails, args.dry_run)
        total_suppressed += n

    print(f"\n{'[DRY RUN] Would have suppressed' if args.dry_run else 'Done. Suppressed'} "
          f"{total_suppressed} addresses across {len(candidates)} workspace(s).")


if __name__ == "__main__":
    main()

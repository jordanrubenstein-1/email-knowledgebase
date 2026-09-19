#!/usr/bin/env python3
"""
Set trade_unsubscribed = true in Braze ID on trade contacts whose unsubscribe was
never honoured, so the trade list can exclude them.

Target definition (all three must hold):
  1. On the ID trade list  -- received a %TRADE% campaign in the last 90 days
  2. Unsubscribed          -- has an email unsubscribe event
  3. Still receiving email -- got a send AFTER their most recent unsubscribe
  4. No "Newsletter Subscribed" custom event after that unsubscribe

Condition 4 is the caller's choice and is worth understanding before relying on it.
Checked 2026-08-21 against this exact population: of the 378 contacts it excludes,
ALL 378 fired their Newsletter Subscribed event within five minutes of cart or
checkout activity, and all 378 alongside Phone Subscribed. None fired standalone.
That pattern is the checkout flow writing subscription state -- the same SDK bug that
resurrects these profiles in the first place -- not somebody opting back in. So the
condition currently protects nobody who demonstrably re-consented, while leaving 378
unsubscribed contacts mailable.

Pass --include-newsletter-resubscribes to drop condition 4 and flag all 716.

Identification is the same two-step as scripts/flag_trade_chronic_bounces.py, whose
resolve_braze_ids / write_attribute helpers this script reuses. No profiles are
created; addresses with no Braze profile are skipped and reported.

Usage:
    uv run python scripts/flag_trade_unsubscribed.py --dry-run
    uv run python scripts/flag_trade_unsubscribed.py --limit 2
    uv run python scripts/flag_trade_unsubscribed.py
    uv run python scripts/flag_trade_unsubscribed.py --include-newsletter-resubscribes
    uv run python scripts/flag_trade_unsubscribed.py --unset
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from flag_trade_chronic_bounces import (  # noqa: E402
    _post,
    resolve_braze_ids,
    write_attribute,
)
from snowflake_client import get_snowflake_client  # noqa: E402
from utils.braze_datashare import get_app_group_id, get_datashare_location  # noqa: E402

BRAND = "ID"
ATTRIBUTE = "trade_unsubscribed"
KEY_ENV = "BRAZE_USERS_API_KEY_ID"
ID_CACHE = REPO / "data" / "trade_unsubscribed_braze_ids.json"


def fetch_targets(include_newsletter_resubs: bool) -> list[dict]:
    db, schema = get_datashare_location(BRAND)
    bz = f"{db}.{schema}"
    app = get_app_group_id(BRAND)
    # With condition 4 dropped, the Newsletter Subscribed timestamp is ignored entirely.
    nl_clause = "" if include_newsletter_resubs else \
        "AND (nl.last_nl IS NULL OR nl.last_nl <= u.last_unsub)"
    sql = f"""
    WITH trade AS (
      SELECT LOWER(EMAIL_ADDRESS) em, MAX(USER_ID) uid
      FROM {bz}.USERS_MESSAGES_EMAIL_SEND_SHARED
      WHERE APP_GROUP_ID='{app}' AND UPPER(CAMPAIGN_NAME) LIKE '%TRADE%'
        AND TO_TIMESTAMP(TIME) >= DATEADD('day',-90,CURRENT_TIMESTAMP())
        AND EMAIL_ADDRESS IS NOT NULL
      GROUP BY 1
    ),
    unsub AS (
      SELECT LOWER(EMAIL_ADDRESS) em, MAX(TO_TIMESTAMP(TIME)) last_unsub,
             COUNT(*) unsub_events
      FROM {bz}.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
      WHERE APP_GROUP_ID='{app}' AND EMAIL_ADDRESS IS NOT NULL
      GROUP BY 1
    ),
    sends AS (
      SELECT LOWER(EMAIL_ADDRESS) em, MAX(TO_TIMESTAMP(TIME)) last_send
      FROM {bz}.USERS_MESSAGES_EMAIL_SEND_SHARED
      WHERE APP_GROUP_ID='{app}' AND EMAIL_ADDRESS IS NOT NULL
      GROUP BY 1
    ),
    nl AS (
      SELECT t.em, MAX(TO_TIMESTAMP(e.TIME)) last_nl
      FROM trade t
      JOIN {bz}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED e ON e.USER_ID = t.uid
      WHERE e.APP_GROUP_ID='{app}' AND e.NAME='Newsletter Subscribed'
      GROUP BY 1
    )
    SELECT t.em AS email,
           u.last_unsub, u.unsub_events, s.last_send,
           DATEDIFF('day', u.last_unsub, s.last_send) AS days_mailed_after_unsub,
           nl.last_nl
    FROM trade t
    JOIN unsub u ON u.em = t.em
    JOIN sends s ON s.em = t.em
    LEFT JOIN nl ON nl.em = t.em
    WHERE s.last_send > u.last_unsub
      {nl_clause}
    ORDER BY days_mailed_after_unsub DESC
    """
    client = get_snowflake_client(schema=schema, database=db)
    return client.execute_query(sql)


def verify(emails: list[str], key: str, sample: int = 30, settle: int = 30) -> None:
    print(f"\nWaiting {settle}s for attribute propagation, then verifying {sample}...")
    time.sleep(settle)
    seen = Counter()
    for email in emails[:sample]:
        status, data = _post(
            "/users/export/ids",
            {"email_address": email, "fields_to_export": ["email", "custom_attributes"]},
            key,
        )
        if status not in (200, 201) or not isinstance(data, dict):
            seen["lookup_failed"] += 1
            continue
        for user in data.get("users", []):
            seen[repr((user.get("custom_attributes") or {}).get(ATTRIBUTE))] += 1
    for value, n in seen.most_common():
        print(f"  {ATTRIBUTE} = {value:<8} {n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--unset", action="store_true",
                    help=f"set {ATTRIBUTE} = false instead of true (rollback)")
    ap.add_argument("--include-newsletter-resubscribes", action="store_true",
                    help="drop condition 4 and flag all 716 still-mailed unsubscribes")
    args = ap.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} not set in .env")
    value = not args.unset

    print("Querying trade contacts still being mailed after unsubscribing...")
    rows = fetch_targets(args.include_newsletter_resubscribes)
    print(f"  {len(rows):,} contacts match")
    if args.include_newsletter_resubscribes:
        print("  (condition 4 dropped -- Newsletter Subscribed re-subscribes included)")

    if rows:
        gaps = [r["DAYS_MAILED_AFTER_UNSUB"] for r in rows if r["DAYS_MAILED_AFTER_UNSUB"] is not None]
        if gaps:
            gaps.sort()
            print(f"  days still mailed after their last unsubscribe: "
                  f"median {gaps[len(gaps)//2]}, max {gaps[-1]}")
        repeat = sum(1 for r in rows if (r["UNSUB_EVENTS"] or 0) > 1)
        print(f"  unsubscribed more than once: {repeat:,}")
        print("\n  longest-running:")
        for r in rows[:5]:
            print(f"    {r['DAYS_MAILED_AFTER_UNSUB']:>4}d  {r['EMAIL'][:44]:<46}"
                  f"{r['UNSUB_EVENTS']} unsub event(s)")

    emails = [r["EMAIL"] for r in rows]
    if args.limit:
        emails = emails[:args.limit]
        print(f"\n  --limit {args.limit}: acting on {len(emails)} address(es) only")

    print("\nResolving braze_ids...")
    id_map = resolve_braze_ids(emails, key, cache_path=ID_CACHE)

    targets: list[str] = []
    no_profile = 0
    for email in emails:
        ids = id_map.get(email)
        if not ids:
            no_profile += 1
            continue
        targets.extend(ids if isinstance(ids, list) else [ids])
    print(f"  {len(emails) - no_profile:,} addresses resolved to {len(targets):,} Braze profiles")
    print(f"  {no_profile:,} addresses have no Braze profile (skipped, none created)")

    if args.dry_run:
        print(f"\n--dry-run: would set {ATTRIBUTE} = {value} on {len(targets):,} profiles")
        return

    print(f"\nSetting {ATTRIBUTE} = {value} on {len(targets):,} profiles...")
    processed, failed = write_attribute(targets, key, value, attribute=ATTRIBUTE)
    print(f"\n  attributes_processed: {processed:,}   failed: {failed:,}")

    if args.verify:
        verify(emails, key)


if __name__ == "__main__":
    main()

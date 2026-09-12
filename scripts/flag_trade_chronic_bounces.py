#!/usr/bin/env python3
"""
Set trade_chronic_bounce = true in Braze ID on the chronic bouncers from the trade list.

Purpose: give the ID trade list a segment exclusion so these addresses stop being
retried. They soft-bounce ~12 times each because Braze classifies the failures as
soft and therefore never suppresses them -- over half are dead domains
(554 5.4.4 Domain Does Not Exist) that will never deliver.

Definition of chronic bouncer, matching scripts/build_trade_migration_list.py:
  >= 3 soft bounces on a %TRADE% campaign in the last 90 days.

ID has no consistent external_id in Braze, so users are identified the same two-step
way scripts/id_pre_arrival_sync.py does it:
  1. /users/export/ids?email_address=X  -> braze_id
  2. /users/track with braze_id         -> set the attribute in place
No profiles are created: an address with no Braze profile is skipped and reported.

Requires BRAZE_USERS_API_KEY_ID (users.export.ids + users.track). The plain
BRAZE_API_KEY_ID is campaign-read-only and returns 403 on both.

Usage:
    uv run python scripts/flag_trade_chronic_bounces.py --dry-run
    uv run python scripts/flag_trade_chronic_bounces.py --limit 2      # live, tiny test
    uv run python scripts/flag_trade_chronic_bounces.py
    uv run python scripts/flag_trade_chronic_bounces.py --verify       # re-read a sample
    uv run python scripts/flag_trade_chronic_bounces.py --unset        # roll back to false
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from snowflake_client import get_snowflake_client  # noqa: E402
from utils.braze_datashare import get_app_group_id, get_datashare_location  # noqa: E402

BRAND = "ID"
ATTRIBUTE = "trade_chronic_bounce"
BRAZE_HOST = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
KEY_ENV = "BRAZE_USERS_API_KEY_ID"
ID_CACHE = REPO / "data" / "trade_chronic_bounce_braze_ids.json"
# Braze accepts up to 75 attribute objects per /users/track request.
TRACK_CHUNK = 75


def fetch_bouncers() -> list[dict]:
    db, schema = get_datashare_location(BRAND)
    bz = f"{db}.{schema}"
    app = get_app_group_id(BRAND)
    sql = f"""
    SELECT LOWER(EMAIL_ADDRESS) AS email,
           COUNT(*)             AS bounce_events,
           MAX(LEFT(BOUNCE_REASON, 90)) AS sample_reason
    FROM {bz}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID='{app}'
      AND UPPER(CAMPAIGN_NAME) LIKE '%TRADE%'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day',-90,CURRENT_TIMESTAMP())
      AND EMAIL_ADDRESS IS NOT NULL
    GROUP BY 1
    HAVING COUNT(*) >= 3
    ORDER BY bounce_events DESC
    """
    client = get_snowflake_client(schema=schema, database=db)
    return client.execute_query(sql)


def _post(path: str, body: dict, key: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        f"{BRAZE_HOST}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(int(exc.headers.get("Retry-After", 5)))
                continue
            if exc.code >= 500 and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            return exc.code, exc.read()[:200].decode()
        except Exception as exc:  # transient network
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            return 0, str(exc)[:200]
    return 0, "retries exhausted"


def resolve_braze_ids(emails: list[str], key: str,
                      cache_path: Path = ID_CACHE) -> dict[str, str | None]:
    """email -> braze_id, or None where no profile exists. Cached and resumable."""
    cache: dict[str, str | None] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    todo = [e for e in emails if e not in cache]
    print(f"  braze_id lookup: {len(cache):,} cached, {len(todo):,} to fetch")

    for i, email in enumerate(todo, 1):
        status, data = _post(
            "/users/export/ids",
            {"email_address": email, "fields_to_export": ["braze_id", "email"]},
            key,
        )
        if status in (200, 201) and isinstance(data, dict):
            users = data.get("users", [])
            # An address can map to several profiles; flag every one of them.
            ids = [u.get("braze_id") for u in users if u.get("braze_id")]
            cache[email] = ids or None
        else:
            cache[email] = None
        if i % 100 == 0 or i == len(todo):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))
            print(f"    {i:,}/{len(todo):,}", flush=True)

    cache_path.write_text(json.dumps(cache))
    return cache


def write_attribute(braze_ids: list[str], key: str, value: bool,
                    attribute: str = ATTRIBUTE) -> tuple[int, int]:
    """Set the attribute on each braze_id. Returns (processed, failed)."""
    processed = failed = 0
    for i in range(0, len(braze_ids), TRACK_CHUNK):
        chunk = braze_ids[i:i + TRACK_CHUNK]
        body = {"attributes": [{"braze_id": bid, attribute: value} for bid in chunk]}
        status, data = _post("/users/track", body, key)
        if status in (200, 201) and isinstance(data, dict):
            processed += data.get("attributes_processed", 0)
            if data.get("errors"):
                print(f"    partial errors: {str(data['errors'])[:200]}")
        else:
            failed += len(chunk)
            print(f"    chunk {i // TRACK_CHUNK + 1} failed: {status} {str(data)[:160]}")
        print(f"    {min(i + TRACK_CHUNK, len(braze_ids)):,}/{len(braze_ids):,}", flush=True)
    return processed, failed


def verify(emails: list[str], key: str, sample: int = 20) -> None:
    print(f"\nVerifying {sample} profiles by re-reading from Braze...")
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
            attrs = user.get("custom_attributes") or {}
            seen[repr(attrs.get(ATTRIBUTE))] += 1
    for value, n in seen.most_common():
        print(f"  {ATTRIBUTE} = {value:<8} {n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="resolve ids, write nothing")
    ap.add_argument("--limit", type=int, help="only act on the first N bouncers")
    ap.add_argument("--verify", action="store_true", help="re-read a sample after writing")
    ap.add_argument("--unset", action="store_true",
                    help=f"set {ATTRIBUTE} = false instead of true (rollback)")
    args = ap.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} not set in .env")
    value = not args.unset

    print("Querying chronic bouncers from the trade list...")
    rows = fetch_bouncers()
    print(f"  {len(rows):,} addresses with >=3 trade soft bounces in 90d")
    total_events = sum(r["BOUNCE_EVENTS"] for r in rows)
    print(f"  {total_events:,} bounce events, {total_events / max(len(rows),1):.1f} per address")
    print("\n  worst offenders:")
    for r in rows[:5]:
        print(f"    {r['BOUNCE_EVENTS']:>3} x  {r['EMAIL'][:42]:<44} {(r['SAMPLE_REASON'] or '')[:52]}")

    emails = [r["EMAIL"] for r in rows]
    if args.limit:
        emails = emails[:args.limit]
        print(f"\n  --limit {args.limit}: acting on {len(emails)} address(es) only")

    print("\nResolving braze_ids...")
    id_map = resolve_braze_ids(emails, key)

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
    processed, failed = write_attribute(targets, key, value)
    print(f"\n  attributes_processed: {processed:,}   failed: {failed:,}")

    if args.verify:
        verify(emails, key)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Force-unsubscribe (global email) the ID users caught repeatedly by the SDK
re-subscribe bug -- see reports/braze-sdk-resubscribe-audit.md.

Population: ID users whose profile was SDK-flipped Subscribed/Opted In after a
prior Unsubscribed state (90-day flip window 2026-05-22 - 2026-08-20), who are
CURRENTLY subscribed, who have unsubscribed (any source) more than once across
their full history, and whose profile is a "clean" single stable identity
(excludes no-identity/no-email profiles, profiles whose EMAIL_ADDRESS switched
mid-history, and known internal/ops accounts) -- same filtering as the chat
analysis this script formalizes.

ID has no consistent external_id in Braze, so users are targeted directly by
braze_id (== USER_ID in the datashare), same method as
scripts/flag_trade_chronic_bounces.py. Requires BRAZE_USERS_API_KEY_ID
(users.track) -- the plain BRAZE_API_KEY_ID is campaign-read-only and 403s.

Usage:
    uv run python scripts/id_unsubscribe_repeat_sdk_resub.py --dry-run
    uv run python scripts/id_unsubscribe_repeat_sdk_resub.py --limit 3   # tiny live test
    uv run python scripts/id_unsubscribe_repeat_sdk_resub.py
    uv run python scripts/id_unsubscribe_repeat_sdk_resub.py --verify   # re-read from Braze
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from snowflake_client import get_snowflake_client  # noqa: E402

TIER3_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
TIER3_SCHEMA = "DATALAKE_SHARING_TIERED"
ID_APP_GROUP = "6666726b459b5e0059d7d687"

BRAZE_HOST = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
KEY_ENV = "BRAZE_USERS_API_KEY_ID"
TRACK_CHUNK = 75  # Braze /users/track limit per request

OUT_CSV = REPO / "data" / "id_sdk_resub_repeat_unsub_remediation.csv"

_INTERNAL_EMAILS = ("orders@havenly.com", "influencerorders@havenly.com", "creativeteam@havenly.com")

POPULATION_QUERY = f"""
WITH history AS (
    SELECT
        USER_ID, TIME, SUBSCRIPTION_STATUS, STATE_CHANGE_SOURCE, EMAIL_ADDRESS,
        LAG(SUBSCRIPTION_STATUS) OVER (PARTITION BY USER_ID ORDER BY TIME) AS PREV_STATUS,
        ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY TIME DESC) AS RN_DESC
    FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED
    WHERE APP_GROUP_ID = '{ID_APP_GROUP}'
),
flips AS (
    SELECT DISTINCT USER_ID
    FROM history
    WHERE STATE_CHANGE_SOURCE = 'SDK'
      AND SUBSCRIPTION_STATUS IN ('Subscribed', 'Opted In')
      AND PREV_STATUS = 'Unsubscribed'
      AND TO_TIMESTAMP(TIME) >= '2026-05-22' AND TO_TIMESTAMP(TIME) < '2026-08-21'
),
current_state AS (
    SELECT USER_ID, SUBSCRIPTION_STATUS AS CURRENT_STATUS, EMAIL_ADDRESS AS LATEST_EMAIL
    FROM history WHERE RN_DESC = 1
),
unsub_counts AS (
    SELECT USER_ID, COUNT(*) AS UNSUB_COUNT
    FROM history WHERE SUBSCRIPTION_STATUS = 'Unsubscribed'
    GROUP BY USER_ID
),
distinct_emails_per_user AS (
    SELECT USER_ID, COUNT(DISTINCT EMAIL_ADDRESS) AS N_DISTINCT_EMAILS
    FROM history
    WHERE EMAIL_ADDRESS IS NOT NULL
    GROUP BY USER_ID
)
SELECT
    f.USER_ID AS BRAZE_ID,
    c.LATEST_EMAIL AS EMAIL,
    c.CURRENT_STATUS,
    u.UNSUB_COUNT
FROM flips f
JOIN current_state c ON c.USER_ID = f.USER_ID
JOIN unsub_counts u ON u.USER_ID = f.USER_ID
LEFT JOIN distinct_emails_per_user d ON d.USER_ID = f.USER_ID
WHERE c.CURRENT_STATUS IN ('Subscribed', 'Opted In')
  AND u.UNSUB_COUNT >= 2
  AND c.LATEST_EMAIL IS NOT NULL
  AND COALESCE(d.N_DISTINCT_EMAILS, 0) <= 1
  AND c.LATEST_EMAIL NOT IN ({", ".join(repr(e) for e in _INTERNAL_EMAILS)})
ORDER BY u.UNSUB_COUNT DESC
"""


def fetch_population() -> list[dict]:
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    return client.execute_query(POPULATION_QUERY)


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
            return exc.code, exc.read()[:300].decode()
        except Exception as exc:  # transient network
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            return 0, str(exc)[:300]
    return 0, "retries exhausted"


def write_unsubscribe(rows: list[dict], key: str) -> tuple[int, int, dict[str, str]]:
    """Sets email_subscribe = 'unsubscribed' via /users/track. Returns (processed, failed, per-braze-id result)."""
    processed = failed = 0
    result_by_id: dict[str, str] = {}
    for i in range(0, len(rows), TRACK_CHUNK):
        chunk = rows[i:i + TRACK_CHUNK]
        body = {"attributes": [{"braze_id": r["BRAZE_ID"], "email_subscribe": "unsubscribed"} for r in chunk]}
        status, data = _post("/users/track", body, key)
        if status in (200, 201) and isinstance(data, dict) and not data.get("errors"):
            processed += len(chunk)
            for r in chunk:
                result_by_id[r["BRAZE_ID"]] = "ok"
        elif status in (200, 201) and isinstance(data, dict):
            # partial: braze doesn't tell us which objects errored, so mark the whole
            # chunk as needing a closer look rather than silently assuming success
            print(f"    partial errors in chunk {i // TRACK_CHUNK + 1}: {str(data['errors'])[:300]}")
            processed += len(chunk)
            for r in chunk:
                result_by_id[r["BRAZE_ID"]] = "ok_with_batch_errors"
        else:
            failed += len(chunk)
            print(f"    chunk {i // TRACK_CHUNK + 1} failed: {status} {str(data)[:200]}")
            for r in chunk:
                result_by_id[r["BRAZE_ID"]] = f"failed:{status}"
        print(f"    {min(i + TRACK_CHUNK, len(rows)):,}/{len(rows):,}", flush=True)
        time.sleep(0.5)
    return processed, failed, result_by_id


def verify(rows: list[dict], key: str) -> None:
    print(f"\nVerifying all {len(rows)} profiles by re-reading from Braze...")
    from collections import Counter
    seen = Counter()
    for r in rows:
        status, data = _post(
            "/users/export/ids",
            {"braze_id": r["BRAZE_ID"], "fields_to_export": ["email", "email_subscribe"]},
            key,
        )
        if status not in (200, 201) or not isinstance(data, dict):
            seen["lookup_failed"] += 1
            continue
        users = data.get("users", [])
        if not users:
            seen["no_profile_returned"] += 1
            continue
        seen[users[0].get("email_subscribe", "MISSING")] += 1
        time.sleep(0.05)
    for value, n in seen.most_common():
        print(f"  email_subscribe = {value!r:<24} {n}")


def load_existing_csv() -> dict[str, dict]:
    if not OUT_CSV.exists():
        return {}
    with OUT_CSV.open() as f:
        return {row["braze_id"]: row for row in csv.DictReader(f)}


def save_csv(rows: list[dict]):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["braze_id", "email", "status_before", "unsub_count_before",
                  "action", "action_timestamp_utc", "action_result",
                  "verify_result", "verify_timestamp_utc"]
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull the population, write the CSV, call no API")
    ap.add_argument("--limit", type=int, help="only act on the first N users (live test)")
    ap.add_argument("--verify", action="store_true",
                     help="re-read from Braze and report email_subscribe state (no writes)")
    args = ap.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} not set in .env")

    if args.verify:
        existing = load_existing_csv()
        if not existing:
            raise SystemExit(f"No existing record at {OUT_CSV} -- run the unsubscribe pass first.")
        rows = [{"BRAZE_ID": bid, **v} for bid, v in existing.items()]
        verify([{"BRAZE_ID": r["braze_id"]} for r in rows], key)
        # update per-row verify result and re-save
        print("\nRe-reading per-user to update the CSV record...")
        for r in rows:
            status, data = _post(
                "/users/export/ids",
                {"braze_id": r["braze_id"], "fields_to_export": ["email_subscribe"]},
                key,
            )
            if status in (200, 201) and isinstance(data, dict) and data.get("users"):
                r["verify_result"] = data["users"][0].get("email_subscribe", "missing")
            else:
                r["verify_result"] = f"lookup_failed:{status}"
            r["verify_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
            time.sleep(0.05)
        save_csv(rows)
        print(f"Updated {OUT_CSV}")
        return

    print("Querying the repeat-unsubscribe population from Snowflake...")
    pop = fetch_population()
    print(f"  {len(pop):,} users (unsubscribed >1x, currently subscribed, clean identity)")

    if args.limit:
        pop = pop[:args.limit]
        print(f"  --limit {args.limit}: acting on {len(pop)} user(s) only")

    now = datetime.now(timezone.utc).isoformat()
    records = [{
        "braze_id": r["BRAZE_ID"],
        "email": r["EMAIL"],
        "status_before": r["CURRENT_STATUS"],
        "unsub_count_before": r["UNSUB_COUNT"],
        "action": "set_email_subscribe_unsubscribed",
        "action_timestamp_utc": now,
        "action_result": "",
        "verify_result": "",
        "verify_timestamp_utc": "",
    } for r in pop]

    if args.dry_run:
        save_csv(records)
        print(f"\n--dry-run: wrote {len(records)} planned rows to {OUT_CSV}, called no API")
        return

    print(f"\nSetting email_subscribe = unsubscribed on {len(pop):,} profiles via /users/track...")
    processed, failed, result_by_id = write_unsubscribe(pop, key)
    print(f"\n  processed: {processed:,}   failed: {failed:,}")

    for rec in records:
        rec["action_result"] = result_by_id.get(rec["braze_id"], "unknown")
    save_csv(records)
    print(f"Saved remediation record to {OUT_CSV}")


if __name__ == "__main__":
    main()

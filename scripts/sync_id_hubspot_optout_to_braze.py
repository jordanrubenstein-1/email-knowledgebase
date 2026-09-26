#!/usr/bin/env python3
"""
Suppress ID (Interior Define) Braze users who have opted out of MARKETING
emails in HubSpot but are still subscribed in Braze.

Source: AIRBYTE_DATABASE.LANDING_HUBSPOT.CONTACTS (the ID HubSpot portal).
NOT PROD.ID_WAREHOUSE.STG_CONTACTS / BASE_HUBSPOT_CONTACTS -- those curated
warehouse tables carry no opt-out columns at all.

The suppression signal is one column:
    PROPERTIES_HS_EMAIL_OPTOUT_71775006 = 'true'

71775006 is ID's MARKETING subscription type in HubSpot. ID has two other
subscription types (72337035, 75608566) that are NOT marketing -- a contact
who opted out of a 1:1 sales email only is still a valid marketing recipient,
and must not be suppressed. PROPERTIES_HS_EMAIL_OPTOUT (opted out of
everything) does not need to be checked separately -- opting out of
everything cascades into all three per-subscription columns, so it is
already a subset of the marketing-optout population above. Confirmed
2026-09-21: every contact with PROPERTIES_HS_EMAIL_OPTOUT = TRUE AND
PROPERTIES_HS_MARKETABLE_STATUS = 'true' is also caught by the query below;
0 counter-examples out of 6,067.

PROPERTIES_HS_MARKETABLE_STATUS = 'true' is layered on top because it is a
much bigger constraint than opt-outs (only 299,943 of 804,413 ID HubSpot
contacts are marketable at all) and matches how the team already reasons
about "real" marketing suppressions.

Gotcha: the per-subscription-type opt-out columns are TEXT, not boolean.
Values are 'true', '' (empty string), or NULL -- test with = 'true'. Empty
string means still subscribed. PROPERTIES_HS_EMAIL_OPTOUT is the one boolean
column and is only ever TRUE or NULL, never FALSE.

ID has no consistent external_id in Braze (see CLAUDE.md "Order Data
Hygiene" -- EXTERNAL_USER_ID looks numeric but does not match the warehouse
CUSTOMER_ID). So Braze users here are targeted directly by braze_id, found
by joining HubSpot's email to the ID TIER3 Braze datashare's own current
subscription-state-per-user view on lowercased email -- same join key and
same view used by scripts/id_unsubscribe_repeat_sdk_resub.py.

This is NOT a pure full-pull-and-diff like scripts/sync_hubspot_trade_to_klaviyo.py,
despite looking like a good fit for that pattern -- confirmed 2026-09-21 that it
cannot be. Writing email_subscribe via /users/track does not generate a row in
USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED (checked directly: 5 users
confirmed email_subscribe = 'unsubscribed' live in Braze still show their last
datashare event as 'Subscribed'/'Opted In', dated months ago, while the view
overall is fresh as of today -- so this is a structural gap in what generates a
row there, not replication lag). That means SUBSCRIPTION_STATUS from the
datashare can never reflect a change this script itself just made, so without a
separate memory of "already handled," every run would re-select and re-process
the exact same population forever -- harmless to end users (re-unsubscribing an
unsubscribed person is a no-op) but it would never converge and would make the
CI logs meaningless (every hourly run would report ~2,000 processed, forever,
with no way to tell a real new opt-out from the same old repeats).

So this script keeps its own ledger instead, in data/id_hubspot_optout_sync_state.yaml
(committed back to the repo by the CI job, same pattern as data/braze_anomaly_state.yaml):
every braze_id this script has ever written to is recorded there and excluded
from the population on every subsequent run, regardless of what the datashare
says about it. Only genuinely new HubSpot opt-outs (never seen by this script
before) get processed each run.

A HubSpot marketing opt-out with NO Braze subscription-state history at all
is left alone by this script (not suppressed, not counted as "still
subscribed"). Confirmed 2026-09-21: none of that population received an ID
email in the prior 90 days, so it is not an active compliance gap -- but
they also don't have a confirmed Braze profile to write to. Revisit if that
turns out to be wrong.

A small fraction of matched profiles (122 of 1,975 in the initial backfill,
~6%) come back with an empty "users" array from /users/export/ids even
though /users/track accepted the write for them -- likely stale/merged
profile IDs surfaced by the datashare's history. These still get recorded in
the ledger (Braze's /users/track response gives no way to distinguish them
from a real success at write time, and retrying a dead ID forever is
pointless), but are flagged with action_result = "no_profile_at_write" so a
human can look into that population separately if it matters.

Usage:
    uv run python scripts/sync_id_hubspot_optout_to_braze.py --dry-run
    uv run python scripts/sync_id_hubspot_optout_to_braze.py --limit 3   # tiny live test
    uv run python scripts/sync_id_hubspot_optout_to_braze.py
    uv run python scripts/sync_id_hubspot_optout_to_braze.py --verify   # re-read from Braze
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

import yaml
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

OUT_CSV = REPO / "data" / "id_hubspot_optout_braze_sync.csv"

# Permanent record of braze_ids this script has already confirmed handled --
# see the module docstring for why this exists (the datashare never reflects
# an email_subscribe write, so without this every run would re-select the
# same population forever). Only entries with a confirmed outcome
# ("unsubscribed" or "no_profile_at_write") go in; anyone still showing
# Subscribed/Opted In after a write attempt is deliberately left out so the
# next run retries them naturally.
STATE_FILE = REPO / "data" / "id_hubspot_optout_sync_state.yaml"

# Known internal/ops accounts -- see CLAUDE.md "Order Data Hygiene (all brands)".
# Belt-and-braces exclusion; unlikely to ever match PROPERTIES_HS_MARKETABLE_STATUS
# = 'true' but cheap to guard against.
_INTERNAL_EMAILS = ("orders@havenly.com", "influencerorders@havenly.com", "creativeteam@havenly.com")

POPULATION_QUERY = f"""
WITH hubspot_optout AS (
    SELECT LOWER(PROPERTIES_EMAIL) AS EMAIL
    FROM AIRBYTE_DATABASE.LANDING_HUBSPOT.CONTACTS
    WHERE PROPERTIES_HS_EMAIL_OPTOUT_71775006 = 'true'
      AND PROPERTIES_HS_MARKETABLE_STATUS = 'true'
      AND PROPERTIES_EMAIL IS NOT NULL
      AND LOWER(PROPERTIES_EMAIL) NOT IN ({", ".join(repr(e) for e in _INTERNAL_EMAILS)})
    GROUP BY 1
),
braze_current AS (
    SELECT
        USER_ID, LOWER(EMAIL_ADDRESS) AS EMAIL, SUBSCRIPTION_STATUS, TIME,
        ROW_NUMBER() OVER (PARTITION BY USER_ID ORDER BY TIME DESC) AS RN
    FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED
    WHERE APP_GROUP_ID = '{ID_APP_GROUP}' AND EMAIL_ADDRESS IS NOT NULL
),
braze_latest AS (
    -- one row per email: the most recently active Braze profile, in case of
    -- duplicate profiles sharing an email address
    SELECT EMAIL, USER_ID, SUBSCRIPTION_STATUS,
           ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY TIME DESC) AS DEDUPE_RN
    FROM braze_current
    WHERE RN = 1
)
SELECT b.USER_ID AS BRAZE_ID, h.EMAIL, b.SUBSCRIPTION_STATUS AS CURRENT_STATUS
FROM hubspot_optout h
JOIN braze_latest b ON b.EMAIL = h.EMAIL AND b.DEDUPE_RN = 1
WHERE b.SUBSCRIPTION_STATUS IN ('Subscribed', 'Opted In')
ORDER BY h.EMAIL
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


def verify_one(braze_id: str, key: str) -> str:
    """Re-reads a single profile from Braze. Returns 'unsubscribed', 'subscribed',
    'opted_in', 'no_profile_returned' (empty users array -- likely a stale/merged
    profile id), or 'lookup_failed:<status>'."""
    status, data = _post(
        "/users/export/ids",
        {"braze_id": braze_id, "fields_to_export": ["email_subscribe"]},
        key,
    )
    if status not in (200, 201) or not isinstance(data, dict):
        return f"lookup_failed:{status}"
    users = data.get("users", [])
    if not users:
        return "no_profile_returned"
    return users[0].get("email_subscribe", "missing")


def verify(rows: list[dict], key: str) -> None:
    print(f"\nVerifying all {len(rows)} profiles by re-reading from Braze...")
    from collections import Counter
    seen = Counter()
    for r in rows:
        seen[verify_one(r["BRAZE_ID"], key)] += 1
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
    fieldnames = ["braze_id", "email", "status_before", "action", "action_timestamp_utc",
                  "action_result", "verify_result", "verify_timestamp_utc"]
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def load_state() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open() as f:
        return yaml.safe_load(f) or {}


def save_state(state: dict[str, dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        yaml.safe_dump(state, f, sort_keys=True, default_flow_style=False)


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
            raise SystemExit(f"No existing record at {OUT_CSV} -- run a sync pass first.")
        rows = [{"BRAZE_ID": bid, **v} for bid, v in existing.items()]
        verify([{"BRAZE_ID": r["braze_id"]} for r in rows], key)
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

    state = load_state()
    print("Querying ID HubSpot-marketing-optout contacts still Subscribed in Braze...")
    all_candidates = fetch_population()
    pop = [r for r in all_candidates if r["BRAZE_ID"] not in state]
    already_handled = len(all_candidates) - len(pop)
    print(f"  {len(all_candidates):,} match the datashare's current-status filter "
          f"({already_handled:,} already in {STATE_FILE.name}, skipped)")
    print(f"  {len(pop):,} new user(s) need suppression this run")

    if not pop:
        print("Nothing to do.")
        return

    if args.limit:
        pop = pop[:args.limit]
        print(f"  --limit {args.limit}: acting on {len(pop)} user(s) only")

    now = datetime.now(timezone.utc).isoformat()
    records = [{
        "braze_id": r["BRAZE_ID"],
        "email": r["EMAIL"],
        "status_before": r["CURRENT_STATUS"],
        "action": "set_email_subscribe_unsubscribed",
        "action_timestamp_utc": now,
        "action_result": "",
        "verify_result": "",
        "verify_timestamp_utc": "",
    } for r in pop]

    if args.dry_run:
        save_csv(records)
        print(f"\n--dry-run: wrote {len(records)} planned rows to {OUT_CSV}, called no API, "
              f"no changes to {STATE_FILE.name}")
        return

    print(f"\nSetting email_subscribe = unsubscribed on {len(pop):,} profile(s) via /users/track...")
    processed, failed, result_by_id = write_unsubscribe(pop, key)
    print(f"\n  processed: {processed:,}   failed: {failed:,}")

    # Re-read each attempted profile so the ledger only ever records a confirmed
    # outcome -- see module docstring for why this can't be inferred from the
    # /users/track response alone.
    print(f"\nVerifying the {len(pop):,} attempted profile(s) against live Braze...")
    now2 = datetime.now(timezone.utc).isoformat()
    confirmed = still_pending = 0
    for i, rec in enumerate(records):
        rec["action_result"] = result_by_id.get(rec["braze_id"], "unknown")
        if rec["action_result"].startswith("failed:"):
            rec["verify_result"] = "skipped_write_failed"
            still_pending += 1
            continue
        outcome = verify_one(rec["braze_id"], key)
        rec["verify_result"] = outcome
        rec["verify_timestamp_utc"] = now2
        if outcome == "unsubscribed":
            state[rec["braze_id"]] = {"email": rec["email"], "result": "unsubscribed", "last_action_utc": now2}
            confirmed += 1
        elif outcome == "no_profile_returned":
            state[rec["braze_id"]] = {"email": rec["email"], "result": "no_profile_at_write", "last_action_utc": now2}
            confirmed += 1
        else:
            # still Subscribed/Opted In, or a lookup failure -- leave out of the
            # ledger entirely so the next run's population query picks it back up
            still_pending += 1
        if (i + 1) % 200 == 0:
            print(f"    verified {i + 1:,}/{len(pop):,}", flush=True)
        time.sleep(0.05)

    save_state(state)
    save_csv(records)
    print(f"\n  confirmed (added to {STATE_FILE.name}): {confirmed:,}   "
          f"left for next run to retry: {still_pending:,}")
    print(f"Saved sync record to {OUT_CSV}")


if __name__ == "__main__":
    main()

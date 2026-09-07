#!/usr/bin/env python3
"""
Auto-unsubscribe staff domain addresses on repeated soft bounce.

Detects @havenly.com / @interiordefine.com / @the-citizenry.com addresses via
two paths against the Braze datashare:
  1. FIRST-EVER soft bounce since the last scan (LAST_RUN_FILE) -- falls back
     to 72h if no prior run on record.
  2. REPEAT bounces: >= REPEAT_MIN_BOUNCES soft bounces in the last
     REPEAT_LOOKBACK_DAYS days, regardless of when the address's true
     first-ever bounce was. This catches chronic bouncers whose first bounce
     happened long before any realistic lookback window and are therefore
     permanently invisible to path 1.

Any address already surfaced by a prior run (via alert or actual unsubscribe)
is recorded in FLAGGED_STATE_FILE, keyed with the most-recent bounce time
known at that point, and excluded from future counts/alerts UNLESS it has
bounced again since -- otherwise the same backlog would re-alert every day
for as long as its old bounce rows remain in the datashare, while an address
that bounces again after being flagged still correctly resurfaces.

LAST_RUN_FILE (the scan anchor) advances on EVERY run, alert or not -- only
the unsubscribe action is gated behind the alert threshold. This prevents the
lookback window from growing unboundedly if the threshold keeps tripping.

Unsubscribes across all 7 platforms:
  Braze:   HAV · ID · BUR (BW) · CZ · STF · TI (legacy)
  Klaviyo: TI · TE

Safety: if more than ALERT_THRESHOLD new (not-already-flagged) addresses are
detected in a single run, the script halts WITHOUT unsubscribing and exits
with code 2 so the calling process (scheduled task) knows to send an alert.

Usage:
    # Dry run — shows what would be unsubscribed, touches nothing
    uv run python scripts/auto_unsub_staff_bounces.py --dry-run

    # Live run (uses timestamp from last run, or 72h fallback)
    uv run python scripts/auto_unsub_staff_bounces.py

    # Force a specific lookback window (overrides timestamp file)
    uv run python scripts/auto_unsub_staff_bounces.py --hours 120
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.snowflake_client import get_snowflake_client

# ── Timestamp file ────────────────────────────────────────────────────────────

# Records the UTC time of the last *scan* (regardless of whether it alerted or
# unsubscribed) so the next run knows exactly how far back to look. Stored
# outside the repo so it persists. Advanced on every run -- see
# record_successful_run() -- so the lookback window can never grow unbounded.
LAST_RUN_FILE = Path.home() / ".claude" / "auto_unsub_last_run.txt"
FALLBACK_HOURS = 72  # used if no prior run on record

# Every address ever surfaced to a human (via an alert OR an actual
# unsubscribe) is recorded here so it never gets re-counted/re-alerted just
# because its historical bounce row is still sitting in the datashare.
# Without this, a stuck LAST_RUN_FILE (or simply re-running with --hours)
# would re-report the same backlog every single day.
FLAGGED_STATE_FILE = Path.home() / ".claude" / "auto_unsub_flagged_addresses.txt"

# ── Safety ────────────────────────────────────────────────────────────────────

ALERT_THRESHOLD = 20  # halt if more than this many new staff bounces in one run

# Second detection path: catches chronic repeat-bouncers whose TRUE first-ever
# bounce happened long before any realistic lookback window (so
# detect_first_bounces() can never see them again), by instead looking for
# addresses with multiple bounce events within a recent rolling window,
# regardless of when they first ever bounced.
REPEAT_LOOKBACK_DAYS = 7
REPEAT_MIN_BOUNCES = 2

# ── Braze ─────────────────────────────────────────────────────────────────────

BRAZE_BASE = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

# All workspaces to unsubscribe from on detection
BRAZE_BRANDS = {
    "HAV": os.environ.get("BRAZE_API_KEY_HAV"),
    "ID":  os.environ.get("BRAZE_USERS_API_KEY_ID"),  # BRAZE_API_KEY_ID lacks email.status; use users key
    "BUR": os.environ.get("BRAZE_API_KEY_BUR"),        # BW = BUR
    "CZ":  os.environ.get("BRAZE_API_KEY_CZ"),
    "STF": os.environ.get("BRAZE_API_KEY_STF"),
    "TI":  os.environ.get("BRAZE_API_KEY_TI"),         # legacy Braze workspace
}

# ── Klaviyo ───────────────────────────────────────────────────────────────────

KLAVIYO_BASE    = "https://a.klaviyo.com/api"
KLAVIYO_VERSION = "2024-10-15"

KLAVIYO_BRANDS = {
    "TI": os.environ.get("KLAVIYO_API_KEY_TI"),
    "TE": os.environ.get("KLAVIYO_API_KEY_TE"),
}

# ── Detection ─────────────────────────────────────────────────────────────────

STAFF_DOMAINS = ["@havenly.com", "@interiordefine.com", "@the-citizenry.com"]

DB     = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
APP_GROUP_IDS = (
    "67093a1f24ebbe0065cb9c77",  # BUR
    "664223fb71bcf3005760dfc2",  # HAV
    "666672a4d8965b005ac6c1bd",  # CZ
)

# Never auto-unsubscribe these addresses (active admin / test accounts)
SAFELIST = {
    "jordan.rubenstein@havenly.com",
    "jordan.rubenstein+brazebot@havenly.com",
}


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def get_lookback_hours(force_hours: int | None) -> tuple[int, str]:
    """
    Returns (hours_to_look_back, description_string).
    Uses the last-run timestamp file unless --hours is explicitly passed.
    Adds a 2-hour buffer to avoid missing bounces at the boundary.
    """
    if force_hours is not None:
        return force_hours, f"forced to {force_hours}h via --hours flag"

    if LAST_RUN_FILE.exists():
        try:
            last_run = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
            delta = datetime.now(timezone.utc) - last_run
            hours = int(delta.total_seconds() / 3600) + 2  # +2h buffer
            since_str = last_run.strftime("%Y-%m-%d %H:%M UTC")
            return hours, f"since last run ({since_str}) + 2h buffer = {hours}h"
        except Exception as e:
            pass  # fall through to fallback

    return FALLBACK_HOURS, f"no prior run on record — using {FALLBACK_HOURS}h fallback"


def record_successful_run(dry_run: bool):
    """
    Write current UTC time to the last-run file after a scan completes --
    called unconditionally (alert path or not), so the lookback window
    resets to a normal ~24-26h day instead of compounding forever. Only the
    *unsubscribe* action is gated behind the alert threshold; the scan
    timestamp always advances.
    """
    if dry_run:
        return
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(timezone.utc).isoformat())


# ── Flagged-address state (already surfaced, don't re-alert) ──────────────────
#
# Stored as {email: iso-timestamp of the most recent bounce known at the time
# it was flagged} rather than a flat set. This matters: a flat set would
# permanently silence an address the first time it's flagged (e.g. on a single
# bounce), even if it later bounces again and becomes a genuine repeat --
# exactly the kind of address detect_repeat_bounces() exists to catch. Keying
# on "has there been a NEWER bounce since we last flagged this" lets an
# address resurface once there's real new signal, while still suppressing
# pure re-detection of the same old historical bounce rows.

def load_flagged_addresses() -> dict[str, str]:
    """Addresses already surfaced in a prior run -> last-known-bounce ISO timestamp."""
    if not FLAGGED_STATE_FILE.exists():
        return {}
    flagged = {}
    for line in FLAGGED_STATE_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        email = parts[0].lower()
        flagged[email] = parts[1] if len(parts) > 1 else ""
    return flagged


def save_flagged_addresses(flagged: dict[str, str], dry_run: bool):
    """Persist the merged {email: last-known-bounce-timestamp} state."""
    if dry_run:
        return
    FLAGGED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{email}\t{last_seen}" for email, last_seen in sorted(flagged.items())]
    FLAGGED_STATE_FILE.write_text("\n".join(lines) + "\n")


def get_latest_bounce_times(emails: list[str]) -> dict[str, str]:
    """MAX bounce time (as a string, for lexical/chronological comparison) per address."""
    if not emails:
        return {}
    app_ids = "', '".join(APP_GROUP_IDS)
    email_list = "', '".join(e.lower().replace("'", "''") for e in emails)
    q = f"""
    SELECT LOWER(EMAIL_ADDRESS) AS email, MAX(TO_TIMESTAMP(TIME))::STRING AS last_bounce
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID IN ('{app_ids}')
      AND LOWER(EMAIL_ADDRESS) IN ('{email_list}')
    GROUP BY LOWER(EMAIL_ADDRESS)
    """
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    rows = client.execute_query(q)
    return {r["EMAIL"]: r["LAST_BOUNCE"] for r in rows}


# ── Helpers ───────────────────────────────────────────────────────────────────

def detect_first_bounces(hours: int) -> list[str]:
    """
    Returns email addresses whose first-ever soft bounce in the datashare
    occurred within the last `hours` hours.
    """
    app_ids = "', '".join(APP_GROUP_IDS)
    domain_clauses = " OR ".join(
        f"LOWER(EMAIL_ADDRESS) LIKE '%{d}'" for d in STAFF_DOMAINS
    )
    q = f"""
    SELECT EMAIL_ADDRESS
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID IN ('{app_ids}')
      AND ({domain_clauses})
      AND EMAIL_ADDRESS NOT LIKE '%deleted-customer%'
    GROUP BY EMAIL_ADDRESS
    HAVING MIN(TO_TIMESTAMP(TIME)) >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    ORDER BY EMAIL_ADDRESS
    """
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    rows = client.execute_query(q)
    return [r["EMAIL_ADDRESS"] for r in rows]


def detect_repeat_bounces(days: int = REPEAT_LOOKBACK_DAYS, min_bounces: int = REPEAT_MIN_BOUNCES) -> list[str]:
    """
    Returns email addresses with >= min_bounces soft-bounce events within the
    last `days` days, regardless of when their first-ever bounce happened.

    Exists because detect_first_bounces() only ever matches an address once,
    on its literal first-ever bounce. A chronic bouncer whose first bounce
    predates any realistic lookback window (e.g. months ago) is otherwise
    permanently invisible to this script even if it keeps bouncing weekly.
    """
    app_ids = "', '".join(APP_GROUP_IDS)
    domain_clauses = " OR ".join(
        f"LOWER(EMAIL_ADDRESS) LIKE '%{d}'" for d in STAFF_DOMAINS
    )
    q = f"""
    SELECT EMAIL_ADDRESS
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID IN ('{app_ids}')
      AND ({domain_clauses})
      AND EMAIL_ADDRESS NOT LIKE '%deleted-customer%'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
    GROUP BY EMAIL_ADDRESS
    HAVING COUNT(*) >= {min_bounces}
    ORDER BY EMAIL_ADDRESS
    """
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    rows = client.execute_query(q)
    return [r["EMAIL_ADDRESS"] for r in rows]


def braze_unsubscribe(email: str, brand: str, api_key: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    url = f"{BRAZE_BASE}/email/status"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers,
                         json={"email": email, "subscription_state": "unsubscribed"},
                         timeout=30)
    resp.raise_for_status()
    return resp.json().get("message") == "success"


def klaviyo_unsubscribe(email: str, brand: str, api_key: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    url = f"{KLAVIYO_BASE}/profile-subscription-bulk-delete-jobs/"
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": KLAVIYO_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "data": {
            "type": "profile-subscription-bulk-delete-job",
            "attributes": {
                "profiles": {
                    "data": [{"type": "profile", "attributes": {"email": email}}]
                }
            },
        }
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    return resp.status_code in (200, 202)


def process_address(email: str, dry_run: bool) -> dict:
    results = {}

    for brand, key in BRAZE_BRANDS.items():
        if not key:
            results[f"braze_{brand}"] = "no_key"
            continue
        try:
            ok = braze_unsubscribe(email, brand, key, dry_run)
            results[f"braze_{brand}"] = "✓" if ok else "✗"
        except Exception as e:
            results[f"braze_{brand}"] = f"error: {e}"
        time.sleep(0.15)

    for brand, key in KLAVIYO_BRANDS.items():
        if not key:
            results[f"klaviyo_{brand}"] = "no_key"
            continue
        try:
            ok = klaviyo_unsubscribe(email, brand, key, dry_run)
            results[f"klaviyo_{brand}"] = "✓" if ok else "✗"
        except Exception as e:
            results[f"klaviyo_{brand}"] = f"error: {e}"
        time.sleep(0.15)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Auto-unsubscribe staff domain addresses on first soft bounce"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be unsubscribed without making changes")
    parser.add_argument("--hours", type=int, default=None,
                        help="Force a specific lookback window in hours (overrides timestamp file)")
    args = parser.parse_args()

    prefix = "[DRY RUN] " if args.dry_run else ""
    hours, lookback_desc = get_lookback_hours(args.hours)
    flagged = load_flagged_addresses()

    print(f"{prefix}Lookback: {lookback_desc}")
    print(f"{prefix}Scanning for first-ever staff domain bounces …")
    first_time = detect_first_bounces(hours)

    print(f"{prefix}Scanning for repeat staff domain bounces "
          f"(>= {REPEAT_MIN_BOUNCES} in last {REPEAT_LOOKBACK_DAYS}d) …")
    repeat = detect_repeat_bounces()

    # Merge both detection paths, tagging why each address showed up.
    reasons: dict[str, set[str]] = {}
    for e in first_time:
        reasons.setdefault(e, set()).add("first_bounce")
    for e in repeat:
        reasons.setdefault(e, set()).add("repeat_bounce")

    # Remove safelisted addresses
    safelisted = [e for e in reasons if e.lower() in SAFELIST]
    for e in safelisted:
        del reasons[e]
    if safelisted:
        print(f"  Safelisted (skipped): {safelisted}")

    # Remove addresses already surfaced in a prior run (alerted or
    # unsubscribed) AND that haven't bounced again since — this is what stops
    # the same backlog re-alerting every day regardless of how large the
    # lookback window has grown, while still letting an address resurface if
    # it genuinely bounces again later (e.g. via detect_repeat_bounces()).
    latest_bounce_times = get_latest_bounce_times(list(reasons))
    already_flagged = {}
    new_reasons = {}
    for e, r in reasons.items():
        key = e.lower()
        prior_seen = flagged.get(key)
        current_latest = latest_bounce_times.get(key)
        if prior_seen and current_latest and current_latest <= prior_seen:
            already_flagged[e] = r
        else:
            new_reasons[e] = r

    if already_flagged:
        print(f"  {len(already_flagged)} address(es) already flagged in a prior run, "
              f"no newer bounce since — excluded from today's count/alert "
              f"(still unresolved if never unsubscribed):")
        for e in sorted(already_flagged):
            print(f"    {e} ({'+'.join(sorted(already_flagged[e]))})")

    candidates = sorted(new_reasons)

    if not candidates:
        print("  No new staff bounces detected beyond what's already been flagged. Nothing to do.")
        record_successful_run(args.dry_run)  # always advance the scan anchor
        return

    print(f"\n  {len(candidates)} new address(es) detected:")
    for e in candidates:
        print(f"    {e} ({'+'.join(sorted(new_reasons[e]))})")

    # Mark everything surfaced today as flagged (with its latest known bounce
    # time), and advance the scan timestamp, REGARDLESS of whether we're
    # about to alert-and-halt or actually unsubscribe. This is the core fix:
    # only the unsubscribe action is gated behind the threshold check below,
    # not the bookkeeping.
    updated_flagged = dict(flagged)
    now_iso = datetime.now(timezone.utc).isoformat()
    for e in candidates:
        updated_flagged[e.lower()] = latest_bounce_times.get(e.lower(), now_iso)
    save_flagged_addresses(updated_flagged, args.dry_run)
    record_successful_run(args.dry_run)

    # Safety check — exit code 2 signals the caller to send an alert
    if len(candidates) > ALERT_THRESHOLD:
        print(f"\n⚠️  ALERT: {len(candidates)} addresses exceeds threshold of {ALERT_THRESHOLD}.")
        print("   This may indicate a Google Workspace / billing outage.")
        print("   No unsubscribes performed. Investigate before running manually with --hours.")
        print(f"   Addresses: {', '.join(candidates)}")
        sys.exit(2)  # caller checks this to trigger Slack alert

    print(f"\n{prefix}Unsubscribing across all platforms …\n")
    total_ok = 0
    total_fail = 0

    for email in candidates:
        print(f"  {email}")
        results = process_address(email, args.dry_run)
        ok_brands   = [k for k, v in results.items() if v == "✓"]
        fail_brands = [k for k, v in results.items() if v not in ("✓", "no_key")]
        skip_brands = [k for k, v in results.items() if v == "no_key"]

        if ok_brands:
            print(f"    ✓ {', '.join(ok_brands)}")
        if fail_brands:
            print(f"    ✗ {', '.join(fail_brands)}")
        if skip_brands:
            print(f"    — no key: {', '.join(skip_brands)}")

        total_ok   += len(ok_brands)
        total_fail += len(fail_brands)

    # (Scan timestamp + flagged-address state were already recorded above,
    # before the threshold check -- so they cover the alert path too.)

    print(f"\n{prefix}Done. {len(candidates)} address(es) processed — "
          f"{total_ok} platform unsubscribes succeeded, {total_fail} failed.")


if __name__ == "__main__":
    main()

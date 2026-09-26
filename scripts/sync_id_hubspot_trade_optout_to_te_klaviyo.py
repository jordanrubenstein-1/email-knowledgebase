#!/usr/bin/env python3
"""
Unsubscribe TE (The Expert) Klaviyo profiles for ID trade members who have
opted out of MARKETING emails in ID HubSpot -- going forward only.

Source: AIRBYTE_DATABASE.LANDING_HUBSPOT.CONTACTS (the ID HubSpot portal).
Same suppression signal as scripts/sync_id_hubspot_optout_to_braze.py:
    PROPERTIES_HS_EMAIL_OPTOUT_71775006 = 'true'   (ID's MARKETING subscription
                                                      type -- not the other two)
    AND PROPERTIES_HS_MARKETABLE_STATUS = 'true'
plus, unique to this script:
    AND PROPERTIES_TRADE_USER = TRUE               (currently a trade member)

`PROPERTIES_TRADE_USER` is the clean, well-populated trade-member flag in ID
HubSpot (37,161 of 804,413 contacts, confirmed 2026-09-22) -- the other two
trade fields aren't useful: PROPERTIES_TRADE_APPLICATION_APPROVED_ has a
single TRUE value sitewide, and PROPERTIES_CURRENT_TRADE_MEMBERSHIP_TIER is
never populated at all.

Why trade members specifically, and why TE: TE (The Expert) is Havenly
Brands' trade-facing brand on a separate Klaviyo account. A trade
professional who works across the portfolio may legitimately want TE content
even after opting out of ID's *consumer* marketing, so this is NOT a blanket
"ID optout -> suppress everywhere" rule -- only trade members are in scope,
on the theory that someone who's both an ID trade contact AND opts out of ID
marketing is signaling they don't want Havenly Brands trade-adjacent email
generally. Confirmed via manual check 2026-09-21/22: of 328 ID-marketing-
optout contacts who were still Subscribed in TE Klaviyo, 265 (81%) were
trade members -- real designer/firm addresses, not accidental overlap.

GRANDFATHER CLAUSE -- this is the load-bearing design decision, confirmed
with Jordan 2026-09-22: do NOT retroactively unsubscribe anyone already in
this population as of the ledger seed date. This script (and its ledger,
data/id_hubspot_trade_optout_te_klaviyo_state.yaml) only acts on trade
members who become newly opted out in ID HubSpot AFTER the seed. Every email
in the population at seed time is written to the ledger with result
"grandfathered_pre_existing" and is never touched by a live run. This is a
different ledger semantic from the Braze sync's ledger (which records
confirmed *actions taken*) -- here an entry can mean either "deliberately
left alone" or "actually unsubscribed."

The write mechanism took real trial and error to land on, 2026-09-22/23 --
worth reading if this script starts misbehaving:
- The "Suppress" action (profile-suppression-bulk-create-jobs) looked right
  and is accepted by the API, but proved unreliable in practice: one real
  profile sat at SUBSCRIBED for almost 24 hours after being submitted, and
  only actually flipped once unsubscribed via Klaviyo's own MCP unsubscribe
  tool instead. This script (via klaviyo_client.py's bulk_unsubscribe_profiles)
  now calls the documented Bulk Unsubscribe Profiles endpoint
  (profile-subscription-bulk-delete-jobs) instead, confirmed end-to-end
  2026-09-23 to land within seconds -- safe to verify in the same run.
- Adding a profile to a Klaviyo list -- even a single-opt-in one, specifically
  tried as a workaround -- actively UN-suppresses and subscribes the profile,
  the opposite of what's wanted, and removing list membership afterward does
  not undo it. Never use list membership for this; only
  bulk_unsubscribe_profiles.

Uses the shared KLAVIYO_API_KEY_TE key -- no new CI/CD variable needed, it's
already configured for the sync-hubspot-trade-to-klaviyo job.

Usage:
    uv run python scripts/sync_id_hubspot_trade_optout_to_te_klaviyo.py --seed-grandfather --dry-run
    uv run python scripts/sync_id_hubspot_trade_optout_to_te_klaviyo.py --seed-grandfather
    uv run python scripts/sync_id_hubspot_trade_optout_to_te_klaviyo.py --dry-run
    uv run python scripts/sync_id_hubspot_trade_optout_to_te_klaviyo.py --limit 3   # tiny live test
    uv run python scripts/sync_id_hubspot_trade_optout_to_te_klaviyo.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO = Path(__file__).parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from snowflake_client import get_snowflake_client  # noqa: E402
from utils.klaviyo_client import KlaviyoClient  # noqa: E402

STATE_FILE = REPO / "data" / "id_hubspot_trade_optout_te_klaviyo_state.yaml"

# Same internal/ops exclusion as the Braze sync, for consistency -- see
# CLAUDE.md "Order Data Hygiene (all brands)".
_INTERNAL_EMAILS = ("orders@havenly.com", "influencerorders@havenly.com", "creativeteam@havenly.com")

POPULATION_QUERY = f"""
    SELECT DISTINCT LOWER(PROPERTIES_EMAIL) AS EMAIL
    FROM AIRBYTE_DATABASE.LANDING_HUBSPOT.CONTACTS
    WHERE PROPERTIES_HS_EMAIL_OPTOUT_71775006 = 'true'
      AND PROPERTIES_HS_MARKETABLE_STATUS = 'true'
      AND PROPERTIES_TRADE_USER = TRUE
      AND PROPERTIES_EMAIL IS NOT NULL
      AND LOWER(PROPERTIES_EMAIL) NOT IN ({", ".join(repr(e) for e in _INTERNAL_EMAILS)})
"""


def fetch_population() -> list[str]:
    client = get_snowflake_client(schema="LANDING_HUBSPOT", database="AIRBYTE_DATABASE")
    return [r["EMAIL"] for r in client.execute_query(POPULATION_QUERY)]


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
    ap.add_argument("--seed-grandfather", action="store_true",
                     help="record the CURRENT population as grandfathered_pre_existing "
                          "(no suppression) and exit -- run this once before the first "
                          "real sync pass, never again")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, call no write API")
    ap.add_argument("--limit", type=int, help="only act on the first N users (live test)")
    args = ap.parse_args()

    key = os.environ.get("KLAVIYO_API_KEY_TE")
    if not key:
        raise SystemExit("KLAVIYO_API_KEY_TE not set in .env")
    klaviyo = KlaviyoClient(key, brand="TE")

    state = load_state()

    print("Querying ID HubSpot trade members opted out of marketing...")
    all_candidates = fetch_population()
    print(f"  {len(all_candidates):,} trade member(s) currently opted out of ID marketing")

    if args.seed_grandfather:
        if state:
            raise SystemExit(
                f"{STATE_FILE.name} already has {len(state):,} entries -- refusing to "
                "re-seed. Delete the file first if you really want to reset the "
                "grandfather baseline (this would let the next sync pass act on "
                "everyone currently in this population)."
            )
        now = datetime.now(timezone.utc).isoformat()
        for email in all_candidates:
            state[email] = {"result": "grandfathered_pre_existing", "last_action_utc": now}
        if args.dry_run:
            print(f"\n--dry-run: would seed {len(state):,} grandfathered entries, wrote nothing")
            return
        save_state(state)
        print(f"\nSeeded {len(state):,} grandfathered entries to {STATE_FILE.name}")
        print("Every trade member currently opted out is now excluded from future runs.")
        return

    pop = [e for e in all_candidates if e not in state]
    already_handled = len(all_candidates) - len(pop)
    print(f"  {already_handled:,} already in {STATE_FILE.name} (grandfathered or previously "
          f"handled), skipped")
    print(f"  {len(pop):,} new trade opt-out(s) to check against TE Klaviyo")

    if not pop:
        print("Nothing to do.")
        return

    if args.limit:
        pop = pop[:args.limit]
        print(f"  --limit {args.limit}: acting on {len(pop)} user(s) only")

    print(f"\nChecking TE Klaviyo consent for {len(pop):,} email(s)...")
    consent = klaviyo.get_email_marketing_consent(pop)

    now = datetime.now(timezone.utc).isoformat()
    to_unsubscribe = []
    for email in pop:
        c = consent.get(email, "NEVER_SUBSCRIBED")  # no profile = never subscribed
        if c == "SUBSCRIBED":
            to_unsubscribe.append(email)
        else:
            # UNSUBSCRIBED already, or NEVER_SUBSCRIBED / no TE profile at all --
            # nothing to do, but record it so we don't re-check every run
            state[email] = {"result": f"no_action_needed:{c.lower()}", "last_action_utc": now}

    print(f"  {len(to_unsubscribe):,} currently Subscribed in TE Klaviyo -- need unsubscribing")

    if args.dry_run:
        print(f"\n--dry-run: would record {len(pop) - len(to_unsubscribe):,} no-action-needed "
              f"entr(ies) and unsubscribe {len(to_unsubscribe):,} profile(s), called no write "
              f"API, no changes to {STATE_FILE.name}")
        for email in to_unsubscribe[:20]:
            print(f"    {email}")
        if len(to_unsubscribe) > 20:
            print(f"    ... and {len(to_unsubscribe) - 20} more")
        return

    if not to_unsubscribe:
        save_state(state)
        print(f"Saved {STATE_FILE.name} ({len(state):,} total entries)")
        return

    print(f"\nSetting email marketing consent = UNSUBSCRIBED for {len(to_unsubscribe):,} "
          f"profile(s) via TE Klaviyo...")
    submitted = klaviyo.bulk_unsubscribe_profiles(to_unsubscribe)
    print(f"  submitted: {submitted:,}/{len(to_unsubscribe):,}")

    print("\nVerifying against live Klaviyo...")
    time.sleep(3)  # brief settle time before re-reading
    verify = klaviyo.get_email_marketing_consent(to_unsubscribe)
    confirmed = still_pending = 0
    now2 = datetime.now(timezone.utc).isoformat()
    for email in to_unsubscribe:
        if verify.get(email) == "UNSUBSCRIBED":
            state[email] = {"result": "unsubscribed", "last_action_utc": now2}
            confirmed += 1
        else:
            # leave out of the ledger -- next run's population query will still
            # include them (still opted out in HubSpot) and retry
            still_pending += 1

    save_state(state)
    print(f"\n  confirmed unsubscribed (added to {STATE_FILE.name}): {confirmed:,}   "
          f"left for next run to retry: {still_pending:,}")
    print(f"Saved {STATE_FILE.name} ({len(state):,} total entries)")


if __name__ == "__main__":
    main()
